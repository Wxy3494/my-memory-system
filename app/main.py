import asyncio
from contextlib import asynccontextmanager, suppress
import re

from fastapi import FastAPI
from app.memory.routes import router as memory_router
from app.memory.limits import MemoryPayloadLimit
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.readiness import readiness
from app.observability import CURRENT, RequestTelemetry, outcome, stage, event, fault_reason
from app import tracing
from pydantic import BaseModel, ConfigDict, Field

from app.mock_data import MOCK_ORDERS, MOCK_REFUNDS
from app.faq_answer import answer_faq
from app.faq_search import search_faq


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1)
    order_id: str | None = None
    refund_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    route: str
    sources: list[str]
    needs_human: bool


class RetrieveRequest(AskRequest):
    question: str = Field(min_length=1, max_length=2000)
    order_id: str | None = Field(default=None, max_length=128)
    refund_id: str | None = Field(default=None, max_length=128)
    top_k: int = Field(default=3, ge=1, le=10, strict=True)


class FAQChunk(BaseModel):
    chunk_id: str
    chunk_no: int
    source: str
    version: str
    start_line: int
    end_line: int
    content: str
    score: float = Field(allow_inf_nan=False)


class RetrieveResponse(BaseModel):
    route: str
    reason: str
    needs_human: bool
    business_result: AskResponse | None = None
    chunks: list[FAQChunk] = Field(default_factory=list)


async def monitor_dependencies():
    previous = None
    while True:
        result, status = await run_in_threadpool(readiness)
        if result != previous:
            event('readiness_changed', status=status, checks=result['checks'])
            previous = result
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(app):
    tracing.configure()
    monitor = asyncio.create_task(monitor_dependencies())
    try:
        yield
    finally:
        monitor.cancel()
        with suppress(asyncio.CancelledError):
            await monitor
        await run_in_threadpool(tracing.shutdown)


app = FastAPI(lifespan=lifespan)
app.add_middleware(MemoryPayloadLimit)
app.add_middleware(RequestTelemetry)
app.include_router(memory_router)


@app.get('/ready')
def ready():
    result, status = readiness()
    return JSONResponse(result, status_code=status)


@app.get('/metrics', include_in_schema=False)
def metrics():
    return Response(generate_latest(), headers={'Content-Type': CONTENT_TYPE_LATEST})



@app.get("/health")
def health():
    return {"status": "ok"}


def answer_request(request: AskRequest) -> AskResponse | None:
    question = request.question

    # 用户明确要求人工处理时，直接提示联系人工。
    if any(word in question for word in ("投诉", "人工客服", "转人工")):
        outcome("handoff", "manual_handoff")
        return AskResponse(
            answer="该问题需要人工客服处理。请联系人工客服，并提供相关单号以便核查。",
            route="handoff",
            sources=[],
            needs_human=True,
        )

    # 判断是否在询问个人退款进度。
    personal_refund = any(
        phrase in question
        for phrase in (
            "我的退款",
            "退款进度",
            "退款状态",
            "退款到哪",
            "退款没到账",
            "我申请的退款",
            "查退款",
        )
    )

    # 判断是否在询问个人订单或物流进度。
    personal_order = (
        any(
            phrase in question
            for phrase in (
                "我的订单",
                "我的物流",
                "我的快递",
                "我的包裹",
                "订单进度",
                "订单状态",
                "物流进度",
                "查订单",
                "查物流",
            )
        )
        or bool(re.search(r"(?:我(?:买|订|下单|购买)的|我这(?:一)?单).*(?:发货|寄出|物流)", question))
    )

    # 先按意图选择查询对象；退款意图优先，避免关联订单号抢占退款查询。
    # 通用政策中的“我想了解发货”不等同于查询个人订单。
    # 个人进度查询缺少单号时，先追问。
    if personal_refund and not request.refund_id:
        outcome("refund_lookup", "missing_refund_id")
        return AskResponse(
            answer="请提供退款单号，以便查询准确的退款状态。",
            route="refund_lookup",
            sources=[],
            needs_human=False,
        )

    if personal_order and not personal_refund and not request.order_id:
        outcome("order_lookup", "missing_order_id")
        return AskResponse(
            answer="请提供订单号，以便查询准确的订单状态。",
            route="order_lookup",
            sources=[],
            needs_human=False,
        )

    # 有明确退款意图时跳过关联订单，随后只查询退款记录。
    if request.order_id and not personal_refund:
        order = MOCK_ORDERS.get(request.order_id)

        if order is None:
            outcome("handoff", "record_not_found")
            return AskResponse(
                answer=(
                    f"未查到模拟订单 {request.order_id}。"
                    "请核对订单号；仍有疑问请联系人工客服。"
                ),
                route="handoff",
                sources=[],
                needs_human=True,
            )

        outcome("order_lookup", "record_found")
        return AskResponse(
            answer=(
                f"模拟订单 {request.order_id} 的状态是"
                f"{order['status']}，更新于 {order['updated_at']}。"
            ),
            route="order_lookup",
            sources=[f"模拟订单记录 {request.order_id}"],
            needs_human=False,
        )

    # 有退款单号时，查询准确记录。
    if request.refund_id:
        refund = MOCK_REFUNDS.get(request.refund_id)

        if refund is None:
            outcome("handoff", "record_not_found")
            return AskResponse(
                answer=(
                    f"未查到模拟退款 {request.refund_id}。"
                    "请核对退款单号；仍有疑问请联系人工客服。"
                ),
                route="handoff",
                sources=[],
                needs_human=True,
            )

        outcome("refund_lookup", "record_found")
        return AskResponse(
            answer=(
                f"模拟退款 {request.refund_id} 的状态是"
                f"{refund['status']}，更新于 {refund['updated_at']}。"
            ),
            route="refund_lookup",
            sources=[f"模拟退款记录 {request.refund_id}"],
            needs_human=False,
        )

    # 通用问题进入 FAQ 检索和 DeepSeek 回答流程。
    return None


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    ctx = CURRENT.get()
    if ctx:
        ctx.question_length = len(request.question)
    with stage('routing'):
        response = answer_request(request)
    if response is None:
        response = AskResponse(**answer_faq(request.question))
    if ctx:
        ctx.source_ids = [source.split(' | ')[0] for source in response.sources
                          if re.fullmatch(r'RULE-[A-Z0-9-]+', source.split(' | ')[0])]
    return response


@app.post('/v1/retrieve', response_model=RetrieveResponse,
          responses={503: {'model': RetrieveResponse, 'description': 'Local retrieval unavailable'}})
def retrieve(request: RetrieveRequest, response: Response) -> RetrieveResponse:
    """Reuse business routing, then retrieve candidates without a generation call."""
    ctx = CURRENT.get()
    if ctx:
        ctx.question_length = len(request.question)
    with stage('routing'):
        business = answer_request(request)
    if business is not None:
        return RetrieveResponse(route=business.route, reason=ctx.reason if ctx else 'business_result',
                                needs_human=business.needs_human, business_result=business)
    try:
        chunks = search_faq(request.question, top_k=request.top_k)
    except Exception as exc:
        reason = fault_reason(exc)
        outcome('handoff', reason, True)
        response.status_code = 503
        return RetrieveResponse(route='handoff', reason=reason, needs_human=True)
    if not chunks:
        outcome('handoff', 'faq_empty', True)
        response.status_code = 503
        return RetrieveResponse(route='handoff', reason='faq_empty', needs_human=True)
    # Candidates are evidence for a later answer, not a claim that it is answerable.
    outcome('faq_retrieval', 'candidates_found')
    return RetrieveResponse(route='faq_retrieval', reason='candidates_found',
                            needs_human=False, chunks=chunks)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
