import unittest
from run import percentile,retrieval_score,score
class EvaluationTests(unittest.TestCase):
    def test_partial_multirule_recall(self):
        result=retrieval_score(['A','B'],['A','C','D'])
        self.assertEqual(result['recall_at_3'],.5)
        self.assertTrue(result['hit_at_3'])
        self.assertEqual(result['rr'],1)
    def test_missing_retrieval(self):
        self.assertEqual(retrieval_score(['A'],['B'])['rr'],0)
    def test_http200_handoff_is_not_faq_success(self):
        checks=score(dict(route='faq_rag',needs_human=False,relevant=['A']),dict(status=200,body=dict(answer='暂不可用',route='handoff',needs_human=True,sources=[])))
        self.assertTrue(checks['http'])
        self.assertFalse(all(checks.values()))
    def test_nearest_rank(self):
        self.assertEqual(percentile([4,1,3,2],.5),2)
        self.assertEqual(percentile([4,1,3,2],.95),4)
        self.assertIsNone(percentile([],.95))
if __name__=='__main__': unittest.main()
