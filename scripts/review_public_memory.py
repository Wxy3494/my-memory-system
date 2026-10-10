"""Credential-free external checks. Does not certify Add/Search or platform acceptance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit


def request(base, path, payload=None, direct=False):
    command = ['curl.exe' if __import__('os').name == 'nt' else 'curl',
               '--silent', '--show-error', '--max-time', '20', '--write-out', '\n%{http_code}',
               '--header', 'Authorization: Bearer acceptance-deliberately-invalid']
    if direct:
        command += ['--noproxy', '*']
    if payload is not None:
        command += ['--header', 'Content-Type: application/json', '--data-binary', '@-']
    # No redirects: credentials and endpoint identity must not move to a different origin.
    result = subprocess.run(command + [base + path], input=json.dumps(payload) if payload else None,
                            capture_output=True, text=True, encoding='utf-8')
    if result.returncode:
        return {'transport_ok': False, 'curl_exit_code': result.returncode}
    body, code = result.stdout.rsplit('\n', 1)
    try:
        value = json.loads(body)
    except ValueError:
        value = None
    return {'transport_ok': True, 'http_status': int(code),
            'body_sha256': hashlib.sha256(body.encode()).hexdigest(), 'json': value}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--direct', action='store_true')
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ('', '/')):
        parser.error('base URL must contain only an HTTP(S) origin, without credentials')
    base = args.base_url.rstrip('/')
    calls = {
        'health': request(base, '/health', direct=args.direct),
        'readiness': request(base, '/ready/memory', direct=args.direct),
        'openapi': request(base, '/openapi.json', direct=args.direct),
        'add_wrong_token': request(base, '/v1/memories/add', {
            'request_id': 'acceptance-invalid-token', 'user_id': 'acceptance-invalid-token',
            'session_id': 'acceptance-invalid-token',
            'messages': [{'role': 'user', 'content': 'Synthetic authentication check.'}]}, args.direct),
        'search_wrong_token': request(base, '/v1/memories/search', {
            'user_id': 'acceptance-invalid-token', 'query': 'Synthetic check', 'top_k': 100}, args.direct),
    }
    schema = calls['openapi'].pop('json', None) or {}
    if not isinstance(schema, dict):
        schema = {}
    calls['openapi']['paths'] = sorted(schema.get('paths', {}))
    checks = {
        'health': calls['health'].get('http_status') == 200 and calls['health'].get('json') == {'status': 'ok'},
        'api_paths': calls['openapi'].get('http_status') == 200 and
                     {'/v1/memories/add', '/v1/memories/search'}.issubset(calls['openapi']['paths']),
        'reject_wrong_add_token': calls['add_wrong_token'].get('http_status') == 401,
        'reject_wrong_search_token': calls['search_wrong_token'].get('http_status') == 401,
    }
    report = {
        'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'base_url': base,
        'transport': 'direct' if args.direct else 'client_default_proxy_configuration',
        'public_checks_passed': all(checks.values()), 'checks': checks, 'responses': calls,
        'authenticated_add_search': 'not_tested', 'platform_smoke': 'not_tested',
        'release_accepted': False,
        'limits': 'No real key read or sent. These checks do not validate model access, retrieval, persistence, capacity, or release identity.',
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'public_checks_passed': report['public_checks_passed'], 'checks': checks,
                      'readiness': calls['readiness'], 'output': str(output)}, ensure_ascii=False))
    return int(not report['public_checks_passed'])


if __name__ == '__main__':
    raise SystemExit(main())
