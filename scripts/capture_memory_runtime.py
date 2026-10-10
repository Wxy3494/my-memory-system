"""Read-only runtime report; explicitly load a secure env file if needed. No probe."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.memory.config import MemoryConfig
from app.memory.runtime import runtime_report
from app.memory.store import PostgresStore


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--env-file"); p.add_argument("--output",required=True)
    args=p.parse_args()
    try:
        if args.env_file:
            from dotenv import load_dotenv
            load_dotenv(args.env_file,override=False)
        config=MemoryConfig.from_env(); PostgresStore(config).check()
        report=runtime_report(config); report["captured_at"]=datetime.now(timezone.utc).isoformat()
        target=Path(args.output)
        if target.exists():
            raise ValueError("existing output")
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(dict(status="captured",source_bundle_sha256=report["source_bundle_sha256"])))
    except Exception as exc:
        print(json.dumps(dict(status="failed",error_type=type(exc).__name__))); raise SystemExit(1)
