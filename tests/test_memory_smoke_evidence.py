"""Failed live acceptance must be recorded without disclosing credentials."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from scripts.memory_smoke import main


class SmokeEvidenceTests(unittest.TestCase):
    def test_unauthorized_failure_is_saved_without_token(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'failed.json'
            transport = httpx.MockTransport(lambda request: httpx.Response(401, json={'detail': 'invalid_memory_token'}))
            client = httpx.Client(base_url='https://example.invalid', transport=transport)
            with patch('sys.argv', ['smoke', '--base-url', 'https://example.invalid', '--output', str(output)]), \
                    patch.dict('os.environ', {'MEMORY_API_KEY': 'secret-test-token-not-for-report'}), \
                    patch('scripts.memory_smoke.httpx.Client', return_value=client), patch('builtins.print'):
                code = main()
            contents = output.read_text(encoding='utf-8')
            report = json.loads(contents)
            self.assertEqual(code, 1)
            self.assertEqual(report['http_status'], 401)
            self.assertEqual(report['completed_checks'], [])
            self.assertNotIn('secret-test-token', contents)
            self.assertNotIn('Authorization', contents)


if __name__ == '__main__':
    unittest.main()
