"""Lightweight competition deployment: no FAQ model, generation, or tracing imports."""
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .memory.routes import router
from .memory.limits import MemoryPayloadLimit
from .observability import RequestTelemetry

app = FastAPI(title="TraceMemory", version="v0")
app.add_middleware(MemoryPayloadLimit)
app.add_middleware(RequestTelemetry)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})
