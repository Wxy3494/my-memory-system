import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

class RoutingRegression(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
    def ask(self,question,**ids):
        response=self.client.post('/ask',json=dict(question=question,**ids))
        self.assertEqual(response.status_code,200)
        return response.json()
    def test_first_person_policy_uses_faq(self):
        answer=dict(answer='现货通常2个工作日发货。',route='faq_rag',sources=['RULE-SHIPPING-01'],needs_human=False)
        for question in ['我想了解现货发货规则，付款后一般多久寄出？','我想问下发货时间，周六算工作日吗？','请给我介绍一下预售商品发货的规定']:
            with self.subTest(question=question),patch('app.main.answer_faq',return_value=answer) as faq:
                self.assertEqual(self.ask(question)['route'],'faq_rag')
                faq.assert_called_once_with(question)
    def test_personal_order_still_requests_id(self):
        for question in ['我的订单发货了吗？','我买的东西什么时候发货？','我这一单寄出了吗？']:
            with self.subTest(question=question),patch('app.main.answer_faq') as faq:
                result=self.ask(question)
                self.assertEqual(result['route'],'order_lookup')
                self.assertIn('请提供订单号',result['answer'])
                faq.assert_not_called()
    def test_refund_intent_wins_over_associated_order(self):
        for question in ['我的退款状态是什么？','帮忙查退款进度','我的订单对应的退款状态呢？']:
            with self.subTest(question=question),patch('app.main.answer_faq') as faq:
                result=self.ask(question,order_id='ORD-1001',refund_id='REF-2001')
                self.assertEqual(result['route'],'refund_lookup')
                self.assertIn('审核中',result['answer'])
                self.assertEqual(result['sources'],['模拟退款记录 REF-2001'])
                faq.assert_not_called()
    def test_refund_missing_or_unknown_never_falls_back_to_order(self):
        missing=self.ask('我的退款状态',order_id='ORD-1001')
        self.assertEqual(missing['route'],'refund_lookup')
        self.assertIn('请提供退款单号',missing['answer'])
        unknown=self.ask('查退款状态',order_id='ORD-1001',refund_id='REF-NONE')
        self.assertEqual(unknown['route'],'handoff')
        self.assertTrue(unknown['needs_human'])
        self.assertEqual(unknown['sources'],[])
    def test_refund_with_order_word_does_not_require_order_id(self):
        result=self.ask('我的订单对应的退款状态呢？',refund_id='REF-2002')
        self.assertEqual(result['route'],'refund_lookup')
        self.assertIn('已退款',result['answer'])
    def test_order_intent_and_explicit_handoff_preserved(self):
        result=self.ask('我的订单发货了吗',order_id='ORD-1001',refund_id='REF-2001')
        self.assertEqual(result['route'],'order_lookup')
        self.assertIn('已发货',result['answer'])
        result=self.ask('我的退款要转人工',order_id='ORD-1001',refund_id='REF-2001')
        self.assertEqual(result['route'],'handoff')
        self.assertTrue(result['needs_human'])
if __name__=='__main__': unittest.main()
