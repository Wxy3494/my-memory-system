"""Start a real lightweight HTTP process without credentials or paid calls."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = dict(os.environ)
    # Synthetic configuration only. Never inherit actual provider keys/DB URLs into this probe.
    for key in tuple(env):
        if key.startswith("MEMORY_") or key in ("DATABASE_URL", "LANGSMITH_TRACING", "LANGSMITH_API_KEY"):
            env.pop(key)
    env["MEMORY_API_KEY"] = "local-launch-test-token"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    output = ROOT / "docs/evidence/20261006-memory"
    output.mkdir(parents=True, exist_ok=True)
    with (output / "launch-server.txt").open("w", encoding="utf-8") as logs:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.memory_main:app", "--host", "127.0.0.1",
                                    "--port", str(port), "--no-access-log"], cwd=ROOT, env=env,
                                   stdout=logs, stderr=logs, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            def get(path):
                try:
                    response = urllib.request.urlopen(f"http://127.0.0.1:{port}" + path, timeout=2)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    return response.status, json.loads(response.read())
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError("API exited")
                try:
                    health_status, health = get("/health")
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(.25)
            else:
                raise RuntimeError("API startup timed out")
            ready_status, ready = get("/ready/memory")
            status, schema = get("/openapi.json")
            assert health_status == 200 and health == {"status": "ok"}
            assert ready_status == 503 and status == 200
            assert {"/v1/memories/add", "/v1/memories/search", "/ready/memory"}.issubset(schema["paths"])
            report = dict(status="passed", real_http_process=True, health_status=health_status,
                          memory_readiness_status=ready_status, readiness=ready, openapi_status=status,
                          provider_calls=0, database_calls=0, faq_model_required=False)
            (output / "launch.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False))
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
