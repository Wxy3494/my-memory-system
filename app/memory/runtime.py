"""Nonsecret runtime identity. Actual source hashes, not only embedding signature."""
import hashlib
from pathlib import Path
from .signals import VERSION


def runtime_report(config):
    root=Path(__file__).resolve().parents[2]
    files=sorted(list((root/"app/memory").glob("*.py"))+list((root/"migrations").glob("*.sql")))
    hashes={str(p.relative_to(root)).replace("\\","/"):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    bundle=hashlib.sha256("\n".join(f"{k}:{v}" for k,v in hashes.items()).encode()).hexdigest()
    return dict(identity_format="runtime-sources-v1",source_sha256=hashes,source_bundle_sha256=bundle,
        required_schema_version=3,signal_parser_version=VERSION,pipeline_signature=config.signature,model=config.model,dimension=config.dimension,
        configuration=dict(retrieval=config.retrieval,neighbor_window=config.neighbor_window,seed_limit=config.seed_limit,
            evidence_bytes=config.evidence_bytes,min_similarity=config.min_similarity,contextual=config.contextual,
            context_limit=config.context_limit,link_hops=config.link_hops,signal_scan_limit=config.signal_scan_limit),
        scope="Actual local files and nonsecret config; image digest and platform version binding require operator verification")
