"""Retrieval contract, generation isolation, failure signals and trace privacy."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.main import app
from app import faq_search, tracing
from app.observability import CURRENT, RequestContext

CHUNK = dict(chunk_id='RULE-SHIPPING-01', chunk_no=1, source='docs/faq.md',
             version='2026-09-30-v3', start_line=19, end_line=23,
             content='PRIVATE_EVIDENCE', score=.75)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_faq_without_key_never_generates(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}), \
                patch('app.main.search_faq', return_value=[CHUNK]) as search, \
                patch('app.main.answer_faq') as answer, patch('app.faq_answer.OpenAI') as provider:
            result = self.client.post('/v1/retrieve', json={'question': '发货规则', 'top_k': 2})
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body['route'], 'faq_retrieval')
        self.assertEqual(body['chunks'], [CHUNK])
        self.assertIsNone(body['business_result'])
        self.assertIn('x-request-id', result.headers)
        search.assert_called_once_with('发货规则', top_k=2)
        answer.assert_not_called()
        provider.assert_not_called()

    def test_business_routing_matches_ask_and_never_retrieves(self):
        cases = [
            {'question': '我的订单状态', 'order_id': 'ORD-1001'},
            {'question': '我的退款状态', 'order_id': 'ORD-1001', 'refund_id': 'REF-2001'},
            {'question': '我的订单状态'},
            {'question': '我的退款状态', 'order_id': 'ORD-1001'},
            {'question': '查询', 'order_id': 'NOT-FOUND'},
            {'question': '转人工'},
        ]
        with patch('app.main.search_faq') as search, patch('app.main.answer_faq') as answer:
            for payload in cases:
                with self.subTest(payload=payload):
                    expected = self.client.post('/ask', json=payload).json()
                    actual = self.client.post('/v1/retrieve', json=payload)
                    self.assertEqual(actual.status_code, 200)
                    self.assertEqual(actual.json()['business_result'], expected)
                    self.assertEqual(actual.json()['chunks'], [])
            search.assert_not_called()
            answer.assert_not_called()

    def test_invalid_input_is_rejected_before_expensive_work(self):
        inputs = [{}, {'question': '  '}, {'question': 'x' * 2001},
                  {'question': 'q', 'order_id': 'x' * 129}]
        inputs += [{'question': 'q', 'top_k': k} for k in (0, 11, True, '3', 1.5)]
        with patch('app.main.search_faq') as search:
            for payload in inputs:
                with self.subTest(payload=payload):
                    result = self.client.post('/v1/retrieve', json=payload)
                    self.assertEqual(result.status_code, 422)
                    self.assertIn('x-request-id', result.headers)
            search.assert_not_called()

    def test_faults_return_503_and_increment_only_retrieval_metrics(self):
        labels = {'route': 'handoff', 'reason': 'database_unavailable', 'technical_failure': 'true'}
        before_ask = REGISTRY.get_sample_value('rag_ask_outcomes_total', labels)
        before_retrieve = REGISTRY.get_sample_value('rag_retrieve_outcomes_total', labels)
        for error, reason in [(RuntimeError('PRIVATE_DSN'), 'database_unavailable'),
                              (faq_search.ModelUnavailable(), 'model_unavailable')]:
            with self.subTest(reason=reason), patch('app.main.search_faq', side_effect=error):
                result = self.client.post('/v1/retrieve', json={'question': '发货规则'})
                self.assertEqual(result.status_code, 503)
                self.assertEqual(result.json()['reason'], reason)
                self.assertTrue(result.json()['needs_human'])
                self.assertEqual(result.json()['chunks'], [])
                self.assertNotIn('PRIVATE_DSN', result.text)
        self.assertEqual(REGISTRY.get_sample_value('rag_ask_outcomes_total', labels), before_ask)
        self.assertEqual(REGISTRY.get_sample_value('rag_retrieve_outcomes_total', labels), before_retrieve + 1)

    def test_empty_index_is_not_a_successful_retrieval(self):
        with patch('app.main.search_faq', return_value=[]):
            result = self.client.post('/v1/retrieve', json={'question': '发货规则'})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json()['reason'], 'faq_empty')

    def test_log_and_trace_correlate_without_raw_text(self):
        exporter = MagicMock()
        def search(*args, **kwargs):
            faq_search.record_retrieval([CHUNK])
            return [CHUNK]
        with patch.object(tracing, 'EXPORTER', exporter), \
                patch('app.main.search_faq', side_effect=search), \
                self.assertLogs('rag.events', level='INFO') as logs:
            result = self.client.post('/v1/retrieve', json={'question': 'PRIVATE_QUESTION'})
        runs = exporter.submit.call_args.args[0]
        root = runs[0]
        self.assertEqual(root['name'], 'retrieve')
        self.assertEqual(root['outputs']['request_id'], result.headers['x-request-id'])
        self.assertEqual(root['outputs']['retrieved_chunks'], [
            {'chunk_id': CHUNK['chunk_id'], 'version': CHUNK['version'], 'score': .75}])
        self.assertNotIn('generation', {run['name'] for run in runs})
        text = json.dumps(runs) + '\n'.join(logs.output)
        self.assertNotIn('PRIVATE_QUESTION', text)
        self.assertNotIn('PRIVATE_EVIDENCE', text)
        self.assertIn(result.headers['x-request-id'], text)

    def test_metadata_filter_and_database_deadline(self):
        ctx = RequestContext('test-id')
        token = CURRENT.set(ctx)
        try:
            faq_search.record_retrieval([CHUNK, {**CHUNK, 'version': 'private@example.com'},
                                        {**CHUNK, 'score': float('nan')},
                                        {**CHUNK, 'source': 'private.txt'}])
            self.assertEqual(len(ctx.retrieved_chunks), 1)
            with patch.dict(os.environ, {'DATABASE_URL': 'test-dsn'}), \
                    patch.object(faq_search, 'get_model') as model, \
                    patch.object(faq_search.psycopg, 'connect') as connect, \
                    patch.object(faq_search, 'register_vector'):
                model.return_value.encode.return_value = [0.0] * 512
                connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [CHUNK]
                self.assertEqual(faq_search.search_faq('问题'), [CHUNK])
                self.assertEqual(connect.call_args.kwargs['options'], '-c statement_timeout=5000')
                sql_args = connect.return_value.__enter__.return_value.execute.call_args.args[1]
                self.assertEqual(sql_args[-1], 3)
        finally:
            CURRENT.reset(token)


if __name__ == '__main__':
    unittest.main()
