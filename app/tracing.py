"""Optional LangSmith REST tracing with a bounded background queue and allowlisted data."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from queue import Queue, Empty, Full
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

from .observability import TRACE_EXPORTS, event

def now():
    return datetime.now(timezone.utc).isoformat()

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class Exporter:
    def __init__(self, endpoint, key, project, workspace='', timeout=2):
        parsed = urlparse(endpoint)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Invalid tracing endpoint')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')):
            raise ValueError('Tracing requires HTTPS or a local test collector')
        self.endpoint, self.key, self.project = endpoint.rstrip('/'), key, project
        self.workspace, self.timeout = workspace, timeout
        self.queue, self.stopped = Queue(maxsize=128), threading.Event()
        self.worker = threading.Thread(target=self._worker, name='rag-trace-export', daemon=True)
        self.worker.start()

    def submit(self, runs):
        if self.stopped.is_set():
            TRACE_EXPORTS.labels('dropped').inc()
            return
        try:
            self.queue.put_nowait(runs)
        except Full:
            TRACE_EXPORTS.labels('dropped').inc()

    def _request(self, method, path, body):
        headers = {'Content-Type': 'application/json', 'x-api-key': self.key}
        if self.workspace:
            headers['x-tenant-id'] = self.workspace
        request = Request(self.endpoint + path, data=json.dumps(body).encode('utf-8'), headers=headers, method=method)
        with build_opener(NoRedirect).open(request, timeout=self.timeout) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError('Trace export refused')

    def _worker(self):
        while not self.stopped.is_set():
            try:
                runs = self.queue.get(timeout=.2)
            except Empty:
                continue
            try:
                for run in runs:
                    create = {k: v for k, v in run.items() if k not in ('end_time', 'outputs', 'error')}
                    create['session_name'] = self.project
                    self._request('POST', '/runs', create)
                for run in runs:
                    update = {k: run[k] for k in ('end_time', 'outputs', 'error') if k in run}
                    self._request('PATCH', '/runs/' + run['id'], update)
                TRACE_EXPORTS.labels('success').inc()
            except Exception as exc:
                TRACE_EXPORTS.labels('error').inc()
                event('trace_export_failed', exception_type=type(exc).__name__)
            finally:
                self.queue.task_done()

    def flush(self, timeout=3):
        deadline = time.monotonic() + timeout
        while self.queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(.02)
        return not self.queue.unfinished_tasks

    def close(self):
        self.flush(2)
        self.stopped.set()
        self.worker.join(timeout=2.5)

class Trace:
    def __init__(self, exporter, request_id, name='ask'):
        self.exporter, self.request_id = exporter, request_id
        self.root = str(uuid.uuid4())
        self.parent = self.root
        self.runs = [{'id': self.root, 'name': name, 'run_type': 'chain',
                      'inputs': {'request_id': request_id}, 'start_time': now(),
                      'extra': {'metadata': {'request_id': request_id, 'payload_policy': 'allowlist_no_raw_text'}}}]

    @contextmanager
    def span(self, name):
        parent, run_id = self.parent, str(uuid.uuid4())
        run = {'id': run_id, 'name': name, 'run_type': 'llm' if name == 'generation' else 'chain',
               'parent_run_id': parent, 'inputs': {'request_id': self.request_id}, 'start_time': now()}
        self.runs.append(run)
        self.parent = run_id
        try:
            yield
        except Exception as exc:
            run['error'] = type(exc).__name__
            raise
        finally:
            run['end_time'], run['outputs'] = now(), {'completed': 'error' not in run}
            self.parent = parent

    def finish(self, summary):
        # Summary is built by middleware from bounded codes, generated IDs and durations.
        self.runs[0].update(end_time=now(), outputs={k: v for k, v in summary.items() if k in ('request_id', 'route', 'reason', 'technical_failure', 'http_status', 'question_length', 'stages_ms', 'source_ids', 'retrieved_chunks')})
        if summary.get('technical_failure'):
            self.runs[0]['error'] = summary.get('reason', 'technical_failure')
        self.exporter.submit(self.runs)

EXPORTER = None

def configure():
    global EXPORTER
    if os.getenv('LANGSMITH_TRACING', '').lower() != 'true':
        return
    key, project = os.getenv('LANGSMITH_API_KEY'), os.getenv('LANGSMITH_PROJECT')
    if not key or not project:
        event('tracing_disabled', reason='missing_configuration')
        TRACE_EXPORTS.labels('disabled').inc()
        return
    try:
        EXPORTER = Exporter(os.getenv('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com'), key, project,
                            os.getenv('LANGSMITH_WORKSPACE_ID', ''))
    except Exception as exc:
        event('tracing_disabled', reason='invalid_configuration', exception_type=type(exc).__name__)
        TRACE_EXPORTS.labels('disabled').inc()

def new_trace(request_id, name='ask'):
    return Trace(EXPORTER, request_id, name) if EXPORTER else None

def shutdown():
    global EXPORTER
    if EXPORTER:
        EXPORTER.close()
        EXPORTER = None
