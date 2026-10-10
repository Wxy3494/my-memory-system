"""Local review manifest; never changes server, Git history, credentials or platform bindings."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.prepare_memory_release import scan
from scripts.memory_private_paths import is_private_path, require_private_git_clear

ROOT=Path(__file__).resolve().parents[1]
EXPORT_ROOTS=("app","migrations","scripts","evals","tests","deploy","docs")
EXPORT_FILES=("README.md","LICENSE","NOTICE.md",".gitignore",".env.example",".env.memory.example",
              "compose.memory.yaml","Dockerfile.memory","Dockerfile.memory-offline",
              "requirements-memory.txt","requirements-memory.lock.txt","requirements-linux.lock.txt")


def source_candidates():
    # Explicit source roots avoid treating an unrelated archived Git checkout as a release file.
    raw=subprocess.check_output(["git","ls-files","--cached","--others","--exclude-standard","-z","--",
                                 *EXPORT_ROOTS,*EXPORT_FILES],cwd=ROOT)
    result=[]
    for name in sorted(set(raw.decode("utf-8").split("\0"))-{ "" } ):
        path=ROOT/name
        if is_private_path(name):
            continue
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT)
                or (path.parts[len(ROOT.parts)] not in EXPORT_ROOTS and name not in EXPORT_FILES)
                or (path.name.startswith(".env") and path.name not in (".env.example",".env.memory.example"))
                or path.suffix in (".whl",".pyc")):
            raise ValueError("unexpected source candidate: "+name)
        result.append((name,path))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    parser.add_argument("--candidate",default="v6-local-review")
    parser.add_argument("--archive",help="Optional NEW zip path inside the ignored releases directory")
    parser.add_argument("--runtime",action="store_true",help="Include nonsecret config from the current explicit process environment")
    args=parser.parse_args()
    target=(ROOT/args.output).resolve()
    if not target.is_relative_to(ROOT):
        parser.error("manifest must stay inside project")
    if target.exists():
        parser.error("manifest already exists; preserve frozen review evidence")
    private_git=require_private_git_clear(ROOT)
    sources=[(name,path) for name,path in source_candidates() if path.resolve()!=target]
    security=scan(sources)
    paths=sorted(set(p for _,p in sources))
    command=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True,check=True)
    status=subprocess.run(["git","status","--porcelain"],cwd=ROOT,capture_output=True,text=True,check=True)
    report=dict(candidate=args.candidate,executed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        timezone="Asia/Shanghai",git_head=command.stdout.strip(),git_worktree_clean=not status.stdout.strip(),
        public_baseline_commit="142f0ddcdd2ccc06b044c47f2777a99d3b3707e9",
        public_repo="https://github.com/Wxy3494/my-memory-system",security=security,private_git=private_git,
        source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        associated_documents={name:hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()
            for name in ("06_项目复评_七项能力与优秀案例_20261007.md","07_复评整改交付_20261007.md",
                         "08_整改后复核评分_20261007.md","09_二轮整改交付与结算清单_20261007.md",
                         "10_二轮整改独立复评_20261007.md","11_三轮整改交付与结算清单_20261007.md",
                         "13_Smoke失分分析_评分细则与整改交接_20261008.md","14_Smoke整改交付与结算清单_20261008.md",
                         "15_v5独立复评_20261008.md","16_v6复评问题整改与结算清单_20261008.md")
            if (ROOT.parent/name).is_file()},
        state="Local changed-worktree manifest, not published/deployed/frozen platform version",
        external_gates={key:"pending" for key in ("public_candidate_commit","api_image_digest","db_image_digest",
            "gateway_image_digest","credential_rotation_record","https_authenticated_roundtrip",
            "restart_roundtrip","cloud_capacity","model_quota","platform_smoke","platform_full")})
    report["historical_platform_smoke"]=dict(run=None,mode="smoke",screenshot_score=53.30,
        candidate_mapping_verified=False,scope="Existing screenshot result, not this candidate's official retest")
    report["external_gates_scope"]="Pending gates refer to the newly frozen candidate, not absence of historical Smoke"
    if args.runtime:
        from app.memory.config import MemoryConfig
        c=MemoryConfig.from_env()
        report["runtime_config"]={"pipeline_signature":c.signature,"model":c.model,"dimension":c.dimension,
            "pipeline_version":c.pipeline_version,"chunk_budget_bytes":c.target,"overlap_bytes":c.overlap,
            "retrieval":c.retrieval,"neighbor_window":c.neighbor_window,"seed_limit":c.seed_limit,
            "evidence_bytes":c.evidence_bytes,"min_similarity":c.min_similarity,"contextual":c.contextual,
            "context_limit":c.context_limit,"link_hops":c.link_hops,"signal_scan_limit":c.signal_scan_limit}
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    if args.archive:
        archive = (ROOT/args.archive).resolve()
        if not archive.is_relative_to(ROOT/"releases") or archive.exists():
            parser.error("use a NEW zip inside releases")
        archive.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED) as output:
            for name,path in sources:
                output.write(path,name)
            output.write(target,str(target.relative_to(ROOT)))
        with zipfile.ZipFile(archive) as output:
            if output.testzip() is not None:
                raise ValueError("archive_integrity_failed")
            for name,path in sources:
                if hashlib.sha256(output.read(name)).hexdigest()!=report["source_hashes"][str(path.relative_to(ROOT))]:
                    raise ValueError("archive_source_hash_failed")
        (archive.parent/(archive.stem+".json")).write_text(json.dumps(dict(
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            archive_bytes=archive.stat().st_size,source_files=len(sources),
            candidate_manifest_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            state="Local review package, not deployed or officially evaluated"),indent=2),encoding="utf-8")
    print(json.dumps({"manifest":str(target),"files":len(paths),"security_findings":len(security["findings"]),
                      "git_worktree_clean":report["git_worktree_clean"]},ensure_ascii=False))


if __name__ == "__main__":
    main()
