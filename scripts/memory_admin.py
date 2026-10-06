"""Explicit migration, paid small probe, and scoped data cleanup. No implicit .env read."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from app.memory.config import MemoryConfig
from app.memory.embeddings import Embeddings
from app.memory.errors import MemoryError
from app.memory.store import PostgresStore


def migrate(config):
    sql = (Path(__file__).resolve().parents[1] / "migrations/001_memory.sql").read_text(encoding="utf-8")
    with psycopg.connect(config.database_url, connect_timeout=5) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(87412061001)")
        conn.execute(sql)
        conn.execute("INSERT INTO memory.schema_version(singleton,version,pipeline_signature) VALUES(true,1,%s) ON CONFLICT DO NOTHING",
                     (config.signature,))
        row = conn.execute("SELECT version,pipeline_signature FROM memory.schema_version WHERE singleton").fetchone()
        if row != (1, config.signature):
            raise MemoryError("memory_migration_or_pipeline_mismatch")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "probe", "purge-user"])
    parser.add_argument("--user-id")
    parser.add_argument("--confirm-user-id")
    args = parser.parse_args()
    try:
        config = MemoryConfig.from_env()
        if args.command == "migrate":
            migrate(config)
        elif args.command == "probe":
            PostgresStore(config).check()
            # Probe in this process cannot populate the API process's probe cache.
            Embeddings(config).encode(["这是自建中文探测文本。", "Synthetic English probe."])
        else:
            if not args.user_id or args.confirm_user_id != args.user_id:
                parser.error("explicit identical --user-id and --confirm-user-id required")
            with PostgresStore(config).connection() as conn:
                result = conn.execute("DELETE FROM memory.ingest_requests WHERE user_id=%s", (args.user_id,))
                print({"deleted_requests": result.rowcount})
        print({"command": args.command, "status": "ok"})
    except Exception as exc:
        print({"status": "failed", "code": exc.code if isinstance(exc, MemoryError) else "admin_dependency_error"})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
