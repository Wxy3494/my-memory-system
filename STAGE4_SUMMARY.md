# 第四阶段验收记录

日期：2026-10-02。用户授权 Codex 实现并执行后续任务，本阶段记为辅助完成。

## 验收结果

| 范围 | 结果与证据 |
| --- | --- |
| Compose 部署 | 步骤 2 已于 2026-10-01 验收，见 `docs/compose-acceptance.md` |
| 存活与就绪 | `/health` 只检查进程；`/ready` 检查数据库、非空 FAQ 和本地 CPU 模型，故障返回 503 |
| 请求日志 | 响应 `X-Request-ID` 与 JSON 日志一致，记录路由、原因码、总耗时和五阶段耗时，保持原有四个业务返回字段 |
| 指标 | HTTP 请求量/错误/直方图、路由与技术失败计数、阶段直方图、依赖就绪、追踪导出状态；未知 URL 使用固定标签 |
| Prometheus | 3.13.3；配置及三条告警规则经 promtool 校验；两个采集目标为 up |
| 首次故障告警 | 固定原因指标先导出零值；新 API 的首次数据库故障经采集后实际触发 RagTechnicalFailure，避免低流量漏报 |
| Grafana | 13.2.3；自动加载 Prometheus 数据源和 12 面板仪表盘，实际浏览器显示依赖状态及延迟图表 |
| LangSmith 线上 | 使用账号现有唯一项目 `rag-api-local-qwen`；远端 API 实际查到 FAQ 和订单父子 run，request_id 与本机日志对应 |
| 追踪脱敏 | 实际检查云端 inputs/outputs：仅请求编号、固定结果码、耗时、问题长度和 FAQ 规则 ID，不含问题/回答/证据原文、单号或密钥 |
| 数据库停机 | 实际停止 db；health=200、ready=503、ask=200 且 handoff、无引用；技术失败计数正确，恢复后 FAQ 正常 |
| 云端故障定位 | 实际数据库故障 run 的原因是 database_unavailable；检索阶段记录 OperationalError，后续生成跳过，可按 trace_id 定位 |
| 模型缓存缺失 | 独立进程指向不存在的缓存目录，ready=503、model_unavailable、问答转人工；正式模型目录未改动 |
| 空 FAQ | 独立临时数据库有表但无规则，ready=503、faq_empty、问答转人工；测试数据库已删除 |
| 监控停机 | 实际停止 Prometheus/Grafana，FAQ 仍正常回答；恢复监控后采集正常 |
| 监控持久化 | 两个监控容器 ID 均改变；同一历史时间点的 Prometheus 查询完全一致，Grafana 数据卷标记保留，数据源和仪表盘恢复 |
| FAQ 数据保留 | 停机恢复后 14 条规则的 ID、正文摘要、向量摘要、版本、行号、内容 hash、模型名等完整快照与演练前一致 |
| 自动化测试 | 17 项 unittest 测试通过，包含多组子场景；供应商超时/鉴权错误、异常输出、非法引用通过受控替身注入验证 |
| 故障隔离 | 本地 REST 收集器实际连接失败和导出队列异常注入均不改变业务返回；追踪后台队列有容量与超时限制 |

## 查看与使用

- API：http://127.0.0.1:8000/docs
- 就绪检查：http://127.0.0.1:8000/ready
- Prometheus：http://127.0.0.1:9090/targets
- Grafana：http://127.0.0.1:3000/d/rag-stage4
- 完整启动、指标含义和排障步骤：`docs/observability.md`

首次获得 LangSmith 项目名时，只查询了 Key 可访问的项目列表，并补充已有唯一项目名；未显示、复制到证据或保存 API Key。追踪配置留在忽略的本机 `.env` 中。

## 证据

原始证据位于忽略目录 `.cache/acceptance/20261002-observability/`：

| 文件 | 证明内容 |
| --- | --- |
| unit-tests.txt | 17 项自动化测试结果 |
| normal-http.json | 真实 HTTP 样例、请求编号、采集目标和仪表盘加载 |
| database-outage.json / database-recovery.json | 数据库停机前后接口行为 |
| before.json / after-db-recovery.json / final-snapshot.json | FAQ 完整快照 |
| metrics-before-fault.txt / metrics-during-fault.txt | 五阶段耗时及 HTTP 200 技术失败指标 |
| model-cache-fault.txt / empty-faq-fault.txt | 独立模型和空库故障 |
| monitor-recovery.json | 监控历史和数据卷保留 |
| first-failure-alert.json | 首次技术故障从零计数并实际触发告警 |
| langsmith-cloud.json / langsmith-fault.json | 云端正常与故障 run、脱敏字段检查 |
| final-runtime.json / final-state.json | 最终镜像、依赖与服务状态 |

这些是本次小规模功能与恢复验收。供应商超时和鉴权故障由测试注入，追踪不可用由本地收集器故障模拟。尚未做固定题集检索评估、并发压测、容量测试、外网部署或生产鉴权；下一阶段应验证检索质量、回答质量和性能。

追踪使用尽力导出的内存队列，网络或停机可丢失记录；Prometheus 历史保留受时间及容量限制。Grafana 为本机匿名 Viewer，配置文件管理面板，无外部告警通知。本次结果不代表生产上线验收。
