#!/usr/bin/env bash
# Run on the server hosting the existing TraceMemory container.
# Uses the container's environment without printing any credentials.
set -euo pipefail
container="${MEMORY_ACCEPT_CONTAINER:-tracememory-api-1}"
evidence="${MEMORY_ACCEPT_OUTPUT:-./memory-acceptance-$(date -u +%Y%m%dT%H%M%SZ)}"
report_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
remote_smoke="/tmp/memory-smoke-${report_id}.json"
remote_restart="/tmp/memory-restart-${report_id}.json"
mkdir -p "$evidence"
docker inspect --format '{{.Id}} {{.Image}} {{.Config.Image}}' "$container" > "$evidence/container-version.txt"
docker exec "$container" python scripts/memory_smoke.py \
  --base-url http://127.0.0.1:8000 --output "$remote_smoke"
docker cp "$container":"$remote_smoke" "$evidence/memory-smoke.json"
curl --noproxy '*' --fail --silent --show-error --max-time 20 \
  -H 'Host: aixuexi.asia' http://127.0.0.1/health > "$evidence/nginx-health.json"
curl --noproxy '*' --fail --silent --show-error --max-time 20 \
  -H 'Host: aixuexi.asia' http://127.0.0.1/ready/memory > "$evidence/nginx-readiness.json"
docker exec -i "$container" python - > "$evidence/runtime-version.json" <<'PY'
import hashlib, json, platform
from pathlib import Path
from app.memory.config import MemoryConfig
from app.memory.store import PostgresStore
c = MemoryConfig.from_env()
with PostgresStore(c).connection() as conn:
    schema = conn.execute('SELECT version FROM memory.schema_version WHERE singleton').fetchone()
    actual_schema = schema['version'] if isinstance(schema, dict) else schema[0]
files = sorted(Path('app/memory').glob('*.py')) + [Path('app/memory_main.py'), Path('app/observability.py')]
files += sorted(Path('migrations').glob('*.sql')) + [Path('requirements-memory.txt'), Path('requirements-memory.lock.txt')]
print(json.dumps({'pipeline_signature': c.signature, 'model': c.model, 'dimension': c.dimension,
                  'pipeline_version': c.pipeline_version, 'retrieval': c.retrieval,
                  'python': platform.python_version(), 'actual_schema_version': actual_schema,
                  'contextual': getattr(c, 'contextual', False),
                  'context_limit': getattr(c, 'context_limit', None),
                  'link_hops': getattr(c, 'link_hops', None),
                  'neighbor_window': c.neighbor_window, 'seed_limit': c.seed_limit,
                  'evidence_bytes': c.evidence_bytes, 'min_similarity': c.min_similarity,
                  'chunk_target': c.target, 'chunk_overlap': c.overlap,
                  'source_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}))
PY
if [[ "${1:-}" == '--restart' ]]; then
  docker restart "$container" > "$evidence/restart.txt"
  # The saved report lives in the same container; this does not recreate or delete it.
  for attempt in {1..30}; do
    if docker exec "$container" python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).close()" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  docker exec "$container" python scripts/memory_smoke.py \
    --base-url http://127.0.0.1:8000 --check-existing "$remote_smoke" \
    --output "$remote_restart"
  docker cp "$container":"$remote_restart" "$evidence/memory-restart.json"
fi
printf 'Server checks completed. Evidence: %s\n' "$evidence"
printf 'Authenticated external Add/Search, capacity, and official platform evaluation remain separate gates.\n'
