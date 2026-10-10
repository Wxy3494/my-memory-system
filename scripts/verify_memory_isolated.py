"""Zero-paid-call verification using a uniquely labelled temporary local PostgreSQL."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid
from urllib.parse import urlunsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    target = Path(args.output_dir).resolve()
    if not target.is_relative_to(ROOT) or target.exists():
        parser.error("use a NEW evidence directory inside the project")
    target.mkdir(parents=True)
    label = "tracememory-round2-" + uuid.uuid4().hex
    container = None
    report = dict(started_at=datetime.now(timezone.utc).isoformat(), label=label,
                  paid_model_calls=0, storage="tmpfs", execution="local_PostgreSQL_fake_vectors")
    def docker(*argv, check=True, env=None):
        return subprocess.run([args.docker, *argv], check=check, capture_output=True,
                              text=True, encoding="utf-8", env=env, timeout=90)
    try:
        password = secrets.token_hex(24)
        child_env = dict(os.environ, POSTGRES_PASSWORD=password)
        container = docker("run", "--detach", "--pull=never", "--name", label,
            "--label", "tracememory.test=" + label, "--publish", "127.0.0.1::5432",
            "--tmpfs", "/var/lib/postgresql/data", "--env", "POSTGRES_PASSWORD",
            "--env", "POSTGRES_DB=round2_memory_test", "pgvector/pgvector:pg17", env=child_env).stdout.strip()
        inspected = json.loads(docker("inspect", container).stdout)[0]
        port = inspected["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
        report.update(container_id=container, image_id=inspected["Image"], local_port=port)
        for attempt in range(40):
            if docker("exec", container, "pg_isready", "-U", "postgres", check=False).returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("temporary_database_not_ready")
        dsn = urlunsplit(("postgresql", f"postgres:{password}@127.0.0.1:{port}", "/round2_memory_test", "", ""))
        env = dict(os.environ, MEMORY_TEST_DATABASE_URL=dsn)
        env.pop("MEMORY_RUN_LIVE_EMBEDDING", None)
        result = subprocess.run([sys.executable, "scripts/verify_memory.py", "--output",
            str(target / "verification.json")], cwd=ROOT, env=env, capture_output=True, timeout=180)
        (target / "verification-console.txt").write_bytes(result.stdout + result.stderr)
        report["verification_exit_code"] = result.returncode
        if result.returncode == 0:
            measured = subprocess.run([sys.executable, "scripts/measure_memory_local.py", "--output",
                str(target / "local-api.json")], cwd=ROOT, env=env, capture_output=True, timeout=180)
            (target / "local-api-console.txt").write_bytes(measured.stdout + measured.stderr)
            report["measurement_exit_code"] = measured.returncode
            suite = subprocess.run([sys.executable, "evals/memory_db_benchmark.py", "--ablation", "--output",
                str(target / "candidate-suite.json")], cwd=ROOT, env=env, capture_output=True, timeout=300)
            (target / "candidate-suite-console.txt").write_bytes(suite.stdout + suite.stderr)
            report["candidate_suite_exit_code"] = suite.returncode
            stability = subprocess.run([sys.executable, "scripts/check_memory_namespaces.py", "--output-dir",
                str(target / "namespace-stability")], cwd=ROOT, env=env, capture_output=True, timeout=300)
            (target / "namespace-console.txt").write_bytes(stability.stdout + stability.stderr)
            report["namespace_stability_exit_code"] = stability.returncode
    except Exception as exc:
        report["error_type"] = type(exc).__name__  # Never print DSNs, env values or subprocess stderr.
    finally:
        if container:
            info = json.loads(docker("inspect", container).stdout)[0]
            if info["Id"] != container or info["Config"]["Labels"].get("tracememory.test") != label:
                raise RuntimeError("temporary_container_identity_mismatch")
            docker("rm", "--force", container)
            report["cleanup"] = "removed_verified_temporary_container"
        report["completed_at"] = datetime.now(timezone.utc).isoformat()
        report["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        (target / "database-runtime.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0 if all(report.get(key) == 0 for key in
        ("verification_exit_code", "measurement_exit_code", "candidate_suite_exit_code", "namespace_stability_exit_code")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
