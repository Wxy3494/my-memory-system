"""Bounded metrics, JSON logs and per-request context; no payloads in labels."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import logging
import time
import uuid

from prometheus_client import Counter, Gauge, Histogram

BUCKETS = (.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, 20, 40, 60)
HTTP_REQUESTS = Counter('rag_http_requests_total', 'HTTP responses', ['method', 'path', 'status'])
HTTP_SECONDS = Histogram('rag_http_request_duration_seconds', 'HTTP duration', ['method', 'path'], buckets=BUCKETS)
OUTCOMES = Counter('rag_ask_outcomes_total', 'Business outcomes including HTTP 200 faults', ['route', 'reason', 'technical_failure'])
RETRIEVE_OUTCOMES = Counter('rag_retrieve_outcomes_total', 'Retrieval-only outcomes', ['route', 'reason', 'technical_failure'])
STAGE_SECONDS = Histogram('rag_stage_duration_seconds', 'Pipeline duration', ['stage'], buckets=BUCKETS)
READY = Gauge('rag_dependency_ready', 'Readiness observed by the 15-second background probe and /ready', ['dependency'])
TRACE_EXPORTS = Counter('rag_trace_exports_total', 'Trace batches', ['status'])
# Export zeros before the first event so rate/increase can observe a first failure.
for route, reasons, technical in (
    ('order_lookup', ('record_found', 'missing_order_id'), False),
    ('refund_lookup', ('record_found', 'missing_refund_id'), False),
    ('handoff', ('manual_handoff', 'record_not_found', 'insufficient_evidence'), False),
    ('handoff', ('generation_not_configured', 'database_unavailable', 'model_unavailable',
                 'faq_empty', 'generation_timeout', 'generation_auth_failed',
                 'generation_connection_failed', 'generation_rate_limited',
                 'invalid_model_output', 'invalid_citation', 'generation_failed'), True),
    ('unresolved', ('validation_error',), False),
    ('unresolved', ('unhandled_error',), True),
):
    for reason in reasons:
        OUTCOMES.labels(route, reason, str(technical).lower())
        if not reason.startswith(('generation_', 'invalid_')) and reason != 'insufficient_evidence':
            RETRIEVE_OUTCOMES.labels(route, reason, str(technical).lower())
OUTCOMES.labels('faq_rag', 'answered', 'false')
RETRIEVE_OUTCOMES.labels('faq_retrieval', 'candidates_found', 'false')
for name in ('routing', 'embedding', 'retrieval', 'generation', 'citation_validation'):
    STAGE_SECONDS.labels(name)
for name in ('database', 'faq', 'model'):
    READY.labels(name).set(0)
for status in ('success', 'error', 'dropped', 'disabled'):
    TRACE_EXPORTS.labels(status)
for status in ('200', '422', '500'):
    HTTP_REQUESTS.labels('POST', '/ask', status)
HTTP_SECONDS.labels('POST', '/ask')
for status in ('200', '422', '500', '503'):
    HTTP_REQUESTS.labels('POST', '/v1/retrieve', status)
HTTP_SECONDS.labels('POST', '/v1/retrieve')
logger = logging.getLogger('rag.events')
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

@dataclass
class RequestContext:
    request_id: str
    route: str = 'unresolved'
    reason: str = 'unset'
    technical_failure: bool = False
    question_length: int = 0
    source_ids: list = field(default_factory=list)
    retrieved_chunks: list = field(default_factory=list)
    stage_ms: dict = field(default_factory=dict)
    trace: object = None

CURRENT = ContextVar('rag_request', default=None)

def event(name, **fields):
    logger.info(json.dumps({'event': name, **fields}, ensure_ascii=False, separators=(',', ':')))

def outcome(route, reason, technical_failure=False):
    ctx = CURRENT.get()
    if ctx:
        ctx.route, ctx.reason, ctx.technical_failure = route, reason, technical_failure

def fault_reason(exc, generation=False):
    # Exception messages can contain connection strings; record only bounded codes.
    name = type(exc).__name__
    if generation:
        return {'APITimeoutError': 'generation_timeout', 'AuthenticationError': 'generation_auth_failed',
                'APIConnectionError': 'generation_connection_failed', 'RateLimitError': 'generation_rate_limited',
                'ValidationError': 'invalid_model_output', 'ModelOutputError': 'invalid_model_output',
                'CitationError': 'invalid_citation'}.get(name, 'generation_failed')
    return 'model_unavailable' if name == 'ModelUnavailable' else 'database_unavailable'

@contextmanager
def stage(name):
    ctx = CURRENT.get()
    start = time.perf_counter()
    manager = ctx.trace.span(name) if ctx and ctx.trace else None
    if manager:
        manager.__enter__()
    error = None
    try:
        yield
    except Exception as exc:
        error = exc
        raise
    finally:
        elapsed = time.perf_counter() - start
        STAGE_SECONDS.labels(name).observe(elapsed)
        if ctx:
            ctx.stage_ms[name] = round(elapsed * 1000, 3)
        if manager:
            manager.__exit__(type(error) if error else None, error, error.__traceback__ if error else None)

class RequestTelemetry:
    """Pure ASGI middleware keeps context through sync endpoints and response errors."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        ctx = RequestContext(str(uuid.uuid4()))
        token = CURRENT.set(ctx)
        scope.setdefault('state', {})['request_id'] = ctx.request_id
        started, status = time.perf_counter(), 500
        response_started = False
        if scope.get('path') in ('/ask', '/v1/retrieve') and scope.get('method') == 'POST':
            from .tracing import new_trace
            ctx.trace = new_trace(ctx.request_id, 'ask' if scope['path'] == '/ask' else 'retrieve')
        async def wrapped_send(message):
            nonlocal status, response_started
            if message['type'] == 'http.response.start':
                response_started = True
                status = message['status']
                message = dict(message)
                message['headers'] = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'x-request-id']
                message['headers'].append((b'x-request-id', ctx.request_id.encode('ascii')))
            await send(message)
        try:
            await self.app(scope, receive, wrapped_send)
        except Exception as exc:
            ctx.reason, ctx.technical_failure = 'unhandled_error', True
            event('request_exception', request_id=ctx.request_id, exception_type=type(exc).__name__)
            if response_started:
                raise
            await wrapped_send({'type': 'http.response.start', 'status': 500,
                                'headers': [(b'content-type', b'application/json')]})
            await wrapped_send({'type': 'http.response.body', 'body': b'{"detail":"Internal service error"}'})
        finally:
            path = getattr(scope.get('route'), 'path', 'unmatched')
            if path not in ('/ask', '/v1/retrieve', '/health', '/ready', '/metrics', '/docs', '/openapi.json', '/redoc',
                            '/v1/memories/add', '/v1/memories/search', '/ready/memory'):
                path = 'unmatched'
            method = scope.get('method')
            if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'):
                method = 'OTHER'
            elapsed = time.perf_counter() - started
            if path != '/metrics':
                HTTP_REQUESTS.labels(method, path, str(status)).inc()
                HTTP_SECONDS.labels(method, path).observe(elapsed)
            if path in ('/v1/memories/add', '/v1/memories/search'):
                event('memory_request_finished', request_id=ctx.request_id, path=path,
                      method=method, status=status, elapsed_ms=round(elapsed * 1000, 3))
            if path in ('/ask', '/v1/retrieve') and method == 'POST':
                if ctx.reason == 'unset':
                    ctx.reason = 'validation_error' if status == 422 else ('http_error' if status >= 400 else 'ok')
                    ctx.technical_failure = status >= 500
                counter = OUTCOMES if path == '/ask' else RETRIEVE_OUTCOMES
                counter.labels(ctx.route, ctx.reason, str(ctx.technical_failure).lower()).inc()
                event('request_finished', request_id=ctx.request_id, trace_id=ctx.trace.root if ctx.trace else None, path=path, method=method, status=status,
                      route=ctx.route, reason=ctx.reason, technical_failure=ctx.technical_failure,
                      question_length=ctx.question_length, elapsed_ms=round(elapsed * 1000, 3), stages_ms=ctx.stage_ms)
                if ctx.trace:
                    try:
                        ctx.trace.finish({'request_id': ctx.request_id, 'route': ctx.route, 'reason': ctx.reason,
                                      'technical_failure': ctx.technical_failure, 'http_status': status,
                                      'question_length': ctx.question_length, 'stages_ms': ctx.stage_ms,
                                      'source_ids': ctx.source_ids, 'retrieved_chunks': ctx.retrieved_chunks})
                    except Exception:
                        TRACE_EXPORTS.labels('dropped').inc()
            CURRENT.reset(token)
