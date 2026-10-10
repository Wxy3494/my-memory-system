"""Reproducible offline regression report. Uses unittest; optional SQL/YAML parsers."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import platform
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))


def main():
    parser = argparse.ArgumentParser()
    started = datetime.now(timezone(timedelta(hours=8)))
    parser.add_argument("--output", default=f"docs/evidence/{started:%Y%m%d-%H%M%S}-verification/verification.json")
    args = parser.parse_args()
    files = list((ROOT / "app/memory").glob("*.py"))
    files += [ROOT / "app/memory_main.py", ROOT / "app/main.py", ROOT / "app/observability.py"]
    files += list((ROOT / "scripts").glob("*.py")) + list((ROOT / "evals").glob("*memory*.py"))
    files += list((ROOT / "tests").glob("test_memory*.py"))
    for path in files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sql_check, yaml_check = "not_installed", "not_installed"
    try:
        from pglast import parse_sql
        for migration in sorted((ROOT / "migrations").glob("*.sql")):
            parse_sql(migration.read_text(encoding="utf-8"))
        # Parse parameterized application SQL as PostgreSQL statements too.
        count = 0
        for path in [ROOT / "app/memory/store.py", ROOT / "scripts/memory_admin.py"]:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executemany") and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        parts = arg.value.split("%s")
                        statement = "".join(p + (f"${i+1}" if i < len(parts)-1 else "") for i, p in enumerate(parts))
                        parse_sql(statement)
                        count += 1
        sql_check = {"migration": "parsed", "application_statements_parsed": count,
                     "limitation": "syntax_only_not_pgvector_execution"}
    except ImportError:
        pass
    try:
        import yaml
        document = yaml.safe_load((ROOT / "compose.memory.yaml").read_text(encoding="utf-8"))
        assert set(document["services"]) == {"db", "migrate", "api", "edge"}
        yaml_check = "parsed_not_docker_runtime_verified"
    except ImportError:
        pass
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([loader.discover(str(ROOT / "tests")), loader.discover(str(ROOT / "evals"), pattern="test_*.py")])
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    (output.parent / "unit-tests.txt").write_text(stream.getvalue(), encoding="utf-8")
    manifest_files = files + list((ROOT / "migrations").glob("*.sql")) + [ROOT / "compose.memory.yaml", ROOT / "Dockerfile.memory",
                             ROOT / "requirements-memory.txt", ROOT / "requirements.txt"]
    report = dict(python=platform.python_version(), date=started.date().isoformat(),
                  started_at=started.isoformat(), completed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                  timezone="Asia/Shanghai", tests_run=result.testsRun,
                  passed=result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
                  skipped=[dict(test=str(test), reason=reason) for test, reason in result.skipped],
                  failures=len(result.failures), errors=len(result.errors), success=result.wasSuccessful(),
                  python_syntax_files=len(files), sql_check=sql_check, compose_yaml=yaml_check,
                  real_database_tests_enabled=bool(os.getenv("MEMORY_TEST_DATABASE_URL")),
                  source_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in manifest_files},
                  limits="Offline contract tests use fakes. Optional DB tests use real PostgreSQL with fake vectors. Real provider/public/platform acceptance requires separate evidence.")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output.parent / (output.stem + "-unit-tests.txt")).write_text(stream.getvalue(), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "source_hashes"}, ensure_ascii=False))
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
