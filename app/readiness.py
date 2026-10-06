"""Readiness tests local dependencies; never invokes the paid generation API."""
import os
import threading

import numpy as np
import psycopg
from .faq_search import get_model, MODEL_NAME, QUERY_PREFIX
from .observability import READY

LOCK = threading.Lock()

class DependencyNotReady(Exception):
    pass

def database_check():
    dsn = os.environ.get('DATABASE_URL')
    if not dsn:
        raise DependencyNotReady('database_not_configured')
    with psycopg.connect(dsn, connect_timeout=2, options='-c statement_timeout=2000') as conn:
        conn.execute('SELECT 1').fetchone()
        return conn.execute("SELECT count(*) FROM faq_chunks WHERE source=%s AND model_name=%s AND vector_dims(embedding)=512", ('docs/faq.md', MODEL_NAME)).fetchone()[0]

def model_check():
    vector = get_model().encode(QUERY_PREFIX + '就绪检查', normalize_embeddings=True)
    if vector.shape != (512,) or not np.isfinite(vector).all():
        raise DependencyNotReady('invalid_model_vector')

def readiness():
    # Avoid simultaneous first model loads; skipped check returns 503, never claims ready.
    if not LOCK.acquire(blocking=False):
        return {'status': 'not_ready', 'checks': {'probe': 'busy'}}, 503
    checks = {}
    try:
        try:
            count = database_check()
            checks['database'] = 'ok'
            checks['faq'] = 'ok' if count > 0 else 'empty'
        except Exception:
            checks.update(database='unavailable', faq='unavailable')
        try:
            model_check()
            checks['model'] = 'ok'
        except Exception:
            checks['model'] = 'unavailable'
        for name, status in checks.items():
            READY.labels(name).set(1 if status == 'ok' else 0)
        ready = all(status == 'ok' for status in checks.values())
        return {'status': 'ready' if ready else 'not_ready', 'checks': checks}, 200 if ready else 503
    finally:
        LOCK.release()
