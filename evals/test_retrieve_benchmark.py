import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from retrieve_benchmark import request_one, summarize


class FakeResponse(io.BytesIO):
    status = 200
    headers = {'X-Request-ID': 'test-request'}


class RetrieveBenchmarkTests(unittest.TestCase):
    def test_summary_includes_failure_latency_and_correct_denominator(self):
        rows = [{'ms': i, 'passed': i != 100} for i in range(1, 101)]
        result = summarize(rows, 2)
        self.assertEqual(result['completed_qps'], 50)
        self.assertEqual(result['successful_qps'], 49.5)
        self.assertEqual(result['error_rate'], .01)
        self.assertEqual(result['p99_ms'], 99)

    def test_http_200_handoff_does_not_count_as_success(self):
        body = {'route': 'handoff', 'needs_human': True, 'chunks': []}
        with patch('retrieve_benchmark.urlopen', return_value=FakeResponse(json.dumps(body).encode())):
            result = request_one('http://localhost', 1, 1)
        self.assertFalse(result['passed'])

    def test_faq_must_contain_expected_rule(self):
        body = {'route': 'faq_retrieval', 'needs_human': False, 'reason': 'candidates_found',
                'chunks': [{'chunk_id': 'RULE-SHIPPING-01'}]}
        with patch('retrieve_benchmark.urlopen', return_value=FakeResponse(json.dumps(body).encode())):
            self.assertTrue(request_one('http://localhost', 1, 1)['passed'])
        body['chunks'] = [{'chunk_id': 'RULE-WRONG-01'}]
        with patch('retrieve_benchmark.urlopen', return_value=FakeResponse(json.dumps(body).encode())):
            self.assertFalse(request_one('http://localhost', 1, 1)['passed'])

    def test_network_and_503_failures_are_preserved_without_raw_errors(self):
        errors = [URLError('PRIVATE_ERROR'),
                  HTTPError('http://localhost', 503, 'unavailable', {}, io.BytesIO(b'{"route":"handoff"}'))]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch('retrieve_benchmark.urlopen', side_effect=error):
                result = request_one('http://localhost', 0, 1)
                self.assertFalse(result['passed'])
                self.assertGreater(result['ms'], 0)
                self.assertNotIn('PRIVATE_ERROR', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
