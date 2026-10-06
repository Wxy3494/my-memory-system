import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import httpx
from openai import APITimeoutError, AuthenticationError
from fastapi.testclient import TestClient
from app.main import app
from app import faq_answer as faq, readiness as checks, tracing
from app.observability import CURRENT, RequestContext
from prometheus_client import REGISTRY

CHUNK={'chunk_id':'RULE-SHIPPING-01','content':'private evidence','source':'docs/faq.md',
       'start_line':19,'end_line':23,'version':'test'}

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.env=patch.dict(os.environ, {'DEEPSEEK_API_KEY':'test-secret', 'LANGSMITH_TRACING':'false'})
        self.env.start()
    def tearDown(self):
        self.env.stop()
    def ask(self, body):
        self.before_outcomes=self.outcome_counts()
        return self.client.post('/ask', json=body)
    def outcome_counts(self):
        counts={}
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if sample.name=='rag_ask_outcomes_total':
                    reason=sample.labels['reason']
                    counts[reason]=counts.get(reason,0)+sample.value
        return counts
    def assertOutcome(self, reason):
        self.assertEqual(self.outcome_counts().get(reason,0),self.before_outcomes.get(reason,0)+1)
    def generated(self, result, finish='stop', error=None, choices=True):
        factory=MagicMock()
        client=factory.return_value.__enter__.return_value
        client.chat.completions.create.return_value=SimpleNamespace(choices=[
            SimpleNamespace(finish_reason=finish,message=SimpleNamespace(content=json.dumps(result)))
        ] if choices else [])
        client.chat.completions.create.side_effect=error
        return factory
    def test_routes_and_request_ids(self):
        cases=[
          ({'question':'我的订单发货了吗','order_id':'ORD-1001'},'order_lookup',False,'record_found'),
          ({'question':'我的订单发货了吗'},'order_lookup',False,'missing_order_id'),
          ({'question':'我的退款进度'},'refund_lookup',False,'missing_refund_id'),
          ({'question':'查询','refund_id':'REF-2002'},'refund_lookup',False,'record_found'),
          ({'question':'查询','order_id':'MISSING-PRIVATE'},'handoff',True,'record_not_found'),
          ({'question':'我要人工客服'},'handoff',True,'manual_handoff')]
        ids=set()
        for body,route,human,reason in cases:
            with self.subTest(reason=reason):
                r=self.ask(body);self.assertEqual(r.status_code,200)
                self.assertEqual(set(r.json()),{'answer','route','sources','needs_human'})
                self.assertEqual(r.json()['route'],route);self.assertEqual(r.json()['needs_human'],human)
                ids.add(r.headers['x-request-id'])
                self.assertOutcome(reason)
        self.assertEqual(len(ids),len(cases))
    def test_validation_and_bounded_labels(self):
        self.assertEqual(self.ask({'question':'  '}).status_code,422)
        self.client.get('/private-customer-123')
        text=self.client.get('/metrics').text
        self.assertNotIn('private-customer-123',text)
        self.assertNotIn('MISSING-PRIVATE',text)
        self.assertIn('path="unmatched"',text)
        self.assertIn('reason="validation_error"',text)
    def test_liveness_independent(self):
        with patch.object(checks,'database_check',side_effect=RuntimeError('secret')):
            self.assertEqual(self.client.get('/health').json(),{'status':'ok'})
    def test_readiness_states(self):
        for count,db_error,model_error,want in [(14,None,None,200),(0,None,None,503),(14,RuntimeError('dsn-secret'),None,503),(14,None,RuntimeError('path-secret'),503)]:
            with self.subTest(count=count,db_error=bool(db_error),model_error=bool(model_error)):
                with patch.object(checks,'database_check',return_value=count,side_effect=db_error),patch.object(checks,'model_check',side_effect=model_error):
                    r=self.client.get('/ready');self.assertEqual(r.status_code,want)
                    self.assertNotIn('secret',r.text)
    def test_missing_generation_configuration(self):
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':''}):
            r=self.ask({'question':'通用问题'})
            self.assertTrue(r.json()['needs_human'])
            self.assertOutcome('generation_not_configured')
    def test_retrieval_failures(self):
        from app.faq_search import ModelUnavailable
        for error,reason in [(RuntimeError('dsn-secret'),'database_unavailable'),(ModelUnavailable(),'model_unavailable')]:
            with patch.object(faq,'search_faq',side_effect=error):
                r=self.ask({'question':'通用问题'})
                self.assertEqual(r.json()['route'],'handoff');self.assertNotIn('secret',r.text)
                self.assertOutcome(reason)
    def test_empty_faq(self):
        with patch.object(faq,'search_faq',return_value=[]),patch.object(faq,'OpenAI') as factory:
            r=self.ask({'question':'通用问题'});self.assertTrue(r.json()['needs_human'])
            factory.assert_not_called()
            self.assertOutcome('faq_empty')
    def test_generation_and_citation_outcomes(self):
        good={'answerable':True,'answer':'supported','used_chunk_ids':['RULE-SHIPPING-01']}
        cases=[(good,'stop',True,'answered'),
          ({**good,'used_chunk_ids':['RULE-INVENTED-01']},'stop',True,'invalid_citation'),
          ({**good,'used_chunk_ids':[]},'stop',True,'invalid_citation'),
          ({**good,'answer':' '},'stop',True,'invalid_citation'),
          ({**good,'answerable':'true'},'stop',True,'invalid_model_output'),
          ({**good,'extra':'private'},'stop',True,'invalid_model_output'),
          ({**good,'answer':'x'*1001},'stop',True,'invalid_model_output'),
          (good,'length',True,'invalid_model_output'),
          (good,'stop',False,'invalid_model_output'),
          ({'answerable':False,'answer':'unknown','used_chunk_ids':[]},'stop',True,'insufficient_evidence')]
        for result,finish,choices,reason in cases:
            with self.subTest(reason=reason,result=result):
                with patch.object(faq,'search_faq',return_value=[CHUNK]),patch.object(faq,'OpenAI',self.generated(result,finish,choices=choices)):
                    r=self.ask({'question':'private customer question'})
                    self.assertEqual(r.status_code,200)
                    self.assertEqual(r.json()['needs_human'],reason!='answered')
                    self.assertOutcome(reason)
                    if reason=='answered':self.assertIn('RULE-SHIPPING-01',r.json()['sources'][0])
    def test_provider_timeout_and_authentication(self):
        req=httpx.Request('POST','https://example.invalid')
        errors=[(APITimeoutError(request=req),'generation_timeout'),
          (AuthenticationError('private-key',response=httpx.Response(401,request=req),body=None),'generation_auth_failed')]
        for error,reason in errors:
            with patch.object(faq,'search_faq',return_value=[CHUNK]),patch.object(faq,'OpenAI',self.generated({},error=error)):
                r=self.ask({'question':'通用问题'});self.assertTrue(r.json()['needs_human'])
                self.assertNotIn('private-key',r.text)
                self.assertOutcome(reason)
    def test_request_log_redaction_and_correlation(self):
        with self.assertLogs('rag.events',level='INFO') as logs:
            r=self.ask({'question':'PRIVATE_BODY_123','order_id':'PRIVATE_ORDER_456'})
        text='\n'.join(logs.output)
        self.assertIn(r.headers['x-request-id'],text)
        self.assertNotIn('PRIVATE_BODY_123',text);self.assertNotIn('PRIVATE_ORDER_456',text)
    def test_unhandled_error_has_safe_body_and_request_id(self):
        with patch('app.main.answer_request',side_effect=RuntimeError('dsn-private-secret')):
            r=self.ask({'question':'test'})
        self.assertEqual(r.status_code,500)
        self.assertIn('x-request-id',r.headers)
        self.assertNotIn('dsn-private-secret',r.text)
        self.assertIn('reason="unhandled_error"',self.client.get('/metrics').text)
    def test_export_queue_failure_does_not_change_answer(self):
        exporter=MagicMock();exporter.submit.side_effect=RuntimeError('private export error')
        with patch.object(tracing,'EXPORTER',exporter):
            r=self.ask({'question':'查询订单','order_id':'ORD-1001'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['route'],'order_lookup')
    def test_trace_chain_and_privacy(self):
        exporter=MagicMock()
        with patch.object(tracing,'EXPORTER',exporter),patch.object(faq,'search_faq',return_value=[CHUNK]),patch.object(faq,'OpenAI',self.generated({'answerable':True,'answer':'private answer','used_chunk_ids':['RULE-SHIPPING-01']})):
            r=self.ask({'question':'private customer question'})
        runs=exporter.submit.call_args.args[0]
        text=json.dumps(runs)
        for private in ['private customer question','private answer','private evidence','test-secret']:
            self.assertNotIn(private,text)
        root=runs[0];self.assertEqual(root['outputs']['request_id'],r.headers['x-request-id'])
        self.assertEqual(root['outputs']['source_ids'],['RULE-SHIPPING-01'])
        self.assertEqual({run['name'] for run in runs},{'ask','routing','generation','citation_validation'})
        ids={run['id'] for run in runs}
        for run in runs[1:]:self.assertIn(run['parent_run_id'],ids)

class TraceExporterTests(unittest.TestCase):
    def test_rest_create_update_and_failure_isolation(self):
        captured=[]
        class Collector(BaseHTTPRequestHandler):
            def do_POST(self):self.capture()
            def do_PATCH(self):self.capture()
            def capture(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                captured.append((self.command,self.path,body))
                self.send_response(200);self.end_headers();self.wfile.write(b'{}')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Collector)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        exporter=tracing.Exporter('http://127.0.0.1:'+str(server.server_port),'private-key','test-project',timeout=.2)
        try:
            trace=tracing.Trace(exporter,'generated-id')
            with trace.span('retrieval'):pass
            trace.finish({'request_id':'generated-id','question':'PRIVATE_QUESTION','route':'faq_rag'})
            self.assertTrue(exporter.flush(3))
            self.assertEqual([item[0] for item in captured],['POST','POST','PATCH','PATCH'])
            self.assertEqual(captured[1][2]['parent_run_id'],trace.root)
            self.assertNotIn('PRIVATE_QUESTION',json.dumps(captured))
            server.shutdown();server.server_close()
            start=time.monotonic();trace=tracing.Trace(exporter,'next-id');trace.finish({'request_id':'next-id'})
            self.assertLess(time.monotonic()-start,.1)
            self.assertTrue(exporter.flush(3))
        finally:
            exporter.close();server.server_close()
    def test_technical_fault_marks_cloud_root_without_raw_error(self):
        exporter=MagicMock()
        trace=tracing.Trace(exporter,'generated-id')
        with self.assertRaises(RuntimeError):
            with trace.span('retrieval'):
                raise RuntimeError('private-database-password')
        trace.finish({'request_id':'generated-id','technical_failure':True,'reason':'database_unavailable'})
        runs=exporter.submit.call_args.args[0]
        self.assertEqual(runs[0]['error'],'database_unavailable')
        self.assertEqual(runs[1]['error'],'RuntimeError')
        self.assertNotIn('private-database-password',json.dumps(runs))
    def test_redirects_and_unsafe_endpoints(self):
        for endpoint in ['http://external.invalid','https://user:secret@example.com','https://example.com/?key=secret']:
            with self.assertRaises(ValueError):tracing.Exporter(endpoint,'key','project')
    def test_disabled_and_missing_key_do_not_break_service(self):
        with patch.dict(os.environ,{'LANGSMITH_TRACING':'true','LANGSMITH_API_KEY':'','LANGSMITH_PROJECT':'p'}):
            tracing.configure();self.assertIsNone(tracing.EXPORTER)
        self.assertEqual(TestClient(app).get('/health').status_code,200)

if __name__=='__main__':unittest.main()
