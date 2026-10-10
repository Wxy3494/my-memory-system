"""Release review must keep failure evidence and never certify a partial check."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.review_public_memory import main


class PublicReviewTests(unittest.TestCase):
    def run_review(self, responses):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'review.json'
            with patch('sys.argv', ['review', '--base-url', 'https://example.invalid', '--output', str(output)]), \
                    patch('scripts.review_public_memory.request', side_effect=responses), patch('builtins.print'):
                code = main()
            return code, json.loads(output.read_text(encoding='utf-8'))

    def test_connection_failure_keeps_report(self):
        code, report = self.run_review([{'transport_ok': False, 'curl_exit_code': 7}] * 5)
        self.assertEqual(code, 1)
        self.assertFalse(report['public_checks_passed'])
        self.assertFalse(report['release_accepted'])

    def test_public_pass_does_not_certify_authenticated_release(self):
        code, report = self.run_review([
            {'http_status': 200, 'json': {'status': 'ok'}},
            {'http_status': 503, 'json': {'status': 'not_ready'}},
            {'http_status': 200, 'json': {'paths': {'/v1/memories/add': {}, '/v1/memories/search': {}}}},
            {'http_status': 401}, {'http_status': 401},
        ])
        self.assertEqual(code, 0)
        self.assertFalse(report['release_accepted'])
        self.assertEqual(report['authenticated_add_search'], 'not_tested')

    def test_bad_schema_and_missing_auth_fail(self):
        code, report = self.run_review([
            {'http_status': 200, 'json': {'status': 'ok'}}, {'http_status': 200},
            {'http_status': 200, 'json': []}, {'http_status': 200}, {'http_status': 200},
        ])
        self.assertEqual(code, 1)
        self.assertFalse(report['checks']['api_paths'])
        self.assertFalse(report['checks']['reject_wrong_add_token'])


if __name__ == '__main__':
    unittest.main()
