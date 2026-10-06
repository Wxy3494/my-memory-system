# 纯检索接口与性能验收

2026-10-03 辅助补充。`POST /v1/retrieve` 复用 `/ask` 的业务路由，个人订单/退款优先查询模拟记录，通用问题调用本地 BGE 和 pgvector。它不调用 DeepSeek，也不判断候选证据足不足以生成答案。

## 契约

```json
{"question":"付款后一般多久发货？","top_k":3}
```

`question` 去除首尾空白后长度为 1–2000，`order_id`、`refund_id` 可选且最长 128 字符，`top_k` 为 1–10 的整数，默认 3。非法输入返回 422。

| 输出 | 含义 |
| --- | --- |
| route | order_lookup、refund_lookup、faq_retrieval 或 handoff |
| reason | 固定结果码，如 record_found、missing_order_id、candidates_found |
| needs_human | 是否建议人工继续处理；false 不代表语义答案一定有依据 |
| business_result | 精确查询、追问或人工提示的原有四字段结果；FAQ 时为 null |
| chunks | 候选 FAQ 列表，包含 ID、正文、版本、行号、块编号和余弦相似度 |

每次响应都有 `X-Request-ID`。个人查询缺单号时追问，未知单号或用户要求人工时停止，不回退 FAQ。数据库/模型不可用、FAQ 空表返回 503、空 chunks 和固定错误码；不暴露异常原文。数据库连接超时 10 秒，单条 SQL 超时 5 秒，这不等于整个请求有 5 秒硬截止。

向量检索返回排名最高的候选，当前没有相似度拒答阈值。无关问题也可能有候选；`/ask` 才执行后续生成与依据校验。`/ask` 原响应四字段保持不变。

Compose 允许 `DEEPSEEK_API_KEY` 留空以运行纯检索；此时 `/ask` 的 FAQ 生成分支按原逻辑返回服务未配置提示。模拟业务接口没有用户鉴权，不用于真实订单数据。

## 监控

- `/v1/retrieve` 使用独立 HTTP path 和 `rag_retrieve_outcomes_total`，不计入 `rag_ask_outcomes_total`。
- Grafana 追加纯检索 QPS、P99 和技术失败率；Prometheus 追加检索技术失败告警。
- LangSmith 根 run 为 `retrieve`，无 generation 子步骤；当前检索元数据只上传格式受限的公开规则 ID、版本和分数，不上传正文。
- 阶段直方图仍聚合两个接口；接口总耗时可按 path 分开，精确分层耗时另看原始样本和追踪。

## 回归与压测

先在项目根目录运行隔离回归（使用已构建镜像中的依赖，不安装 Windows 包、不读取 `.env`）：

```powershell
./evals/check.ps1
```

代码修改后构建并更新 API，再等待 `/ready` 返回 200：

```powershell
docker compose build api
docker compose up -d --no-build --wait --wait-timeout 60 api
```

运行标准库负载脚本，结果名必须不存在：

```powershell
python ./evals/retrieve_benchmark.py --requests 1000 --concurrency 4 --output ./docs/evidence/retrieve-run-01.json
```

脚本固定 50% 精确查询、50% FAQ；4 次预热不计入测量，预热失败则停止负载并保存失败信息。保留每次状态、路由、命中规则 ID、请求编号及耗时，按实际总墙钟计算完成 QPS、成功 QPS、错误率及 nearest-rank P50/P95/P99。HTTP 200 转人工不会算成功，失败耗时不从分位数中剔除。`by_route` 的 QPS 是该路径对整组总吞吐的贡献，分母仍为整组墙钟。

这是固定并发、有限请求数的闭环负载，无法证明开放到达流量下的容量上限。正式指标验收需要逐级并发、足够持续时间并保留失败样本；同时记录服务端镜像、CPU/RAM、FAQ 数量、监控开关和客户端位置。结果中的源码摘要仅来自运行脚本所在目录，服务端版本要另外核对。

当前仅缓存模型实例，没有问题向量、查询结果或答案缓存。重复问题不能标为“缓存命中”。原计划中的缓存命中/未命中对照，须在实现缓存及失效策略后另做；当前不宣称 200+ QPS 或 P99＜500ms 已达标。

## 历史证据

`docs/evidence/20261003-career-run/` 是补充前版本的完整问答结果，保留原始响应和核验记录。此次修改不会自动重跑真实生成服务。旧 verifier 默认检查当前源码摘要，代码变化后会报告版本不符；不要在原证据目录重跑它来覆盖原 `verification.json`。若需复核，复制证据到新目录并记录对应源码版本，或按新版本另跑一组结果。
