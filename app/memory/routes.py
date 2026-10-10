import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import MemoryConfig
from .embeddings import Embeddings, upstream_status
from .errors import MemoryError
from .schemas import AddRequest, AddResponse, SearchRequest, SearchResponse
from .service import MemoryService
from .store import PostgresStore

router = APIRouter(tags=["TraceMemory"])


def authorize(request: Request):
    import os
    key = os.getenv("MEMORY_API_KEY", "")
    if not key:
        raise HTTPException(503, "memory_auth_not_configured")
    actual = request.headers.get("authorization", "")
    if not hmac.compare_digest(actual.encode(), ("Bearer " + key).encode()):
        raise HTTPException(401, "invalid_memory_token", headers={"WWW-Authenticate": "Bearer"})


def get_service():
    try:
        config = MemoryConfig.from_env()
        return MemoryService(config, PostgresStore(config), Embeddings(config))
    except MemoryError as exc:
        raise HTTPException(exc.status, exc.code) from None


@router.get("/v1/memories/version",dependencies=[Depends(authorize)])
def memory_version(service=Depends(get_service)):
    from .runtime import runtime_report
    try:
        service.store.check()
        return runtime_report(service.config)
    except MemoryError as exc:
        raise HTTPException(exc.status,exc.code) from None


@router.post("/v1/memories/add", response_model=AddResponse, dependencies=[Depends(authorize)])
def add_memory(request: AddRequest, service=Depends(get_service)):
    try:
        return service.add(request)
    except MemoryError as exc:
        raise HTTPException(exc.status, exc.code) from None


@router.post("/v1/memories/search", response_model=SearchResponse, dependencies=[Depends(authorize)])
def search_memory(request: SearchRequest, service=Depends(get_service)):
    try:
        return service.search(request)
    except MemoryError as exc:
        raise HTTPException(exc.status, exc.code) from None


@router.get("/ready/memory")
def ready_memory():
    checks = {}
    try:
        config = MemoryConfig.from_env()
        checks["configuration"] = "ok"
        PostgresStore(config).check()
        checks["database_and_migration"] = "ok"
        checks["embedding"] = upstream_status(config)
    except MemoryError as exc:
        checks["dependency"] = exc.code
    ready = checks.get("embedding") == "ok" and "dependency" not in checks
    reason = "ok" if ready else ("probe_missing_or_expired" if checks.get("embedding") == "not_probed_or_expired"
                                  else "dependency_failure")
    return JSONResponse({"status": "ready" if ready else "not_ready", "checks": checks,
                         "readiness_reason": reason,
                         "configuration_database_ready": checks.get("database_and_migration") == "ok"},
                        status_code=200 if ready else 503)
