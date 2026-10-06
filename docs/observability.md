# 第四阶段运行与排障

本项目的本机部署使用 PostgreSQL、FastAPI、Prometheus 和 Grafana。监控配置保存在 `monitoring/`，监控数据使用各自命名卷；原 FAQ 使用外部卷 `rag_pgdata`。所有宿主机端口仅绑定 `127.0.0.1`。

## 启动与访问

在项目根目录执行，Docker 不在 PATH 时用本机 Docker 可执行文件路径替换 `docker`：

```powershell
docker compose --profile monitoring up -d --build --wait --wait-timeout 120 db api prometheus grafana
docker compose --profile monitoring ps
```

| 入口 | 用途 |
| --- | --- |
| http://127.0.0.1:8000/docs | 手动测试问答 |
| http://127.0.0.1:8000/health | API 进程存活 |
| http://127.0.0.1:8000/ready | 数据库、非空 FAQ 和本地模型就绪 |
| http://127.0.0.1:8000/metrics | Prometheus 指标 |
| http://127.0.0.1:9090/targets | 查看采集目标 |
| http://127.0.0.1:3000/d/rag-stage4 | Grafana 运维仪表盘 |

Grafana 是本机演示用的匿名 Viewer，没有创建初始管理员，仪表盘由配置文件提供。需要修改面板时编辑 `monitoring/grafana/dashboards/rag-stage4.json`，约 30 秒轮询加载后刷新浏览器查看。当前使用 `updateIntervalSeconds: 30`：大于 10 秒时强制轮询，避免 Windows Docker 挂载的文件变更事件遗漏；修改 provider 配置后需重启 Grafana。机制见 [Grafana 官方说明](https://grafana.com/docs/grafana/latest/administration/provisioning/#detect-updates-to-provisioned-dashboards-files)。该配置用于本机开发，外部部署应另行配置访问认证。

普通 `docker compose up` 仍只启用 api、db；监控通过 `monitoring` profile 启用。FAQ 入库单独执行：

```powershell
docker compose run --rm --no-deps index
```

这要求数据库已经运行。入库成功后，用 `/ready` 和一个有引用的 FAQ 问答分别验证依赖与业务。

## 日志和指标

每个 HTTP 响应带 `X-Request-ID`；JSON 请求日志包含同一编号、路由、固定原因码、HTTP 状态、技术失败标记、总耗时和阶段耗时。开启追踪时另有 `trace_id`。日志不记录问题、答案、订单号、退款单号和密钥；Uvicorn 访问日志关闭，避免动态 URL 原样写入日志。

```powershell
docker compose logs --tail 100 api
docker compose logs --tail 100 db
docker compose logs --tail 100 prometheus grafana
```

| 指标 | 标签与用途 |
| --- | --- |
| rag_http_requests_total | method、固定 path、status；请求量和 HTTP 错误 |
| rag_http_request_duration_seconds | method、固定 path；直方图计算 P95/P99 |
| rag_ask_outcomes_total | route、reason、technical_failure；业务结果与技术故障 |
| rag_retrieve_outcomes_total | 纯检索接口的路由、结果与技术故障，不混入问答指标 |
| rag_stage_duration_seconds | routing、embedding、retrieval、generation、citation_validation；阶段直方图 |
| rag_dependency_ready | database、faq、model；15 秒后台检查及 `/ready` 的最近结果 |
| rag_trace_exports_total | success、error、dropped、disabled；追踪导出批次 |

`/ask` 返回 200 的转人工结果可能来自技术故障，不能只看 HTTP 5xx。人工请求、记录未找到和证据不足属于普通业务结果；数据库不可用、模型不可用、空 FAQ、生成超时、鉴权失败、无效模型输出或引用错误计入技术失败。

标签不包含问题原文、单号或请求编号。未知 URL 统一记为 `unmatched`。阶段指标是进程累计值，API 重建后会重置；Prometheus `rate`/`increase` 能处理计数器重置。P95/P99 是基于桶的近似值，少量演示请求不代表容量或性能验收。

Prometheus 每 5 秒采集，保留 7 天且存储目标限制为 256 MB。固定原因、阶段和导出状态预先导出零值，让首次事件也能参与增量计算。它有 API 不可采集、依赖未就绪、问答技术失败和纯检索技术失败四条告警规则。技术失败告警回看最近五分钟，故障演练后的告警会随窗口消退。这里只在 Prometheus/Grafana 展示告警，未配置 Alertmanager 或外部通知。

2026-10-03 追加三个纯检索面板，按 `/v1/retrieve` 展示 QPS、P99 和技术失败率。告警文件修改后需要重启 Prometheus 使规则生效；Grafana 文件面板由 provisioning 自动加载。

## LangSmith

真实配置保留在本机 `.env`，模板见 `.env.example`。启用需要 `LANGSMITH_TRACING=true`、`LANGSMITH_API_KEY`、`LANGSMITH_PROJECT`；区域通过 `LANGSMITH_ENDPOINT` 指定，组织级 Key 如有要求再填写 `LANGSMITH_WORKSPACE_ID`。修改后用 `docker compose up -d --no-build --wait api` 让新配置进入容器。

使用 LangSmith REST 创建父子 run。FAQ 问答包含五个阶段，单号查询只经过分流，纯检索没有生成阶段。上传的输入只有生成的请求编号；输出包括固定路由/原因、技术失败、HTTP 状态、问题长度、阶段耗时、引用规则 ID，以及受限格式的公开候选规则 ID/版本/分数。异常只上传类型名或固定原因码。技术故障会标记根 run 错误，可按日志中的 `trace_id` 定位。

导出使用容量 128 的后台队列、单次网络超时 2 秒，不阻塞业务请求。无配置、远端错误或队列满会记录状态并保留业务返回。它是尽力导出：没有持久队列及重试保证，停机或网络故障可能丢失追踪。

## 定位与恢复

1. 查看 `/health`、`/ready`，判断是进程故障还是本地依赖故障。
2. 从响应取得 `X-Request-ID`，在 API JSON 日志定位固定原因和耗时。
3. 在 Grafana 查看技术失败、依赖和阶段延迟；有追踪时按 `trace_id` 查看失败阶段。
4. 数据库故障先恢复 db，再检查 `/ready` 和 FAQ 实际回答；缺模型应恢复原完整本地缓存；空 FAQ 应运行独立 index。
5. 生成超时或鉴权故障应检查供应商状态和本机配置；追踪导出故障检查 LangSmith 配置和网络。不要通过打印环境变量或完整 Compose 配置排查密钥。

容器重建不会删除命名卷。停止服务用 `docker compose --profile monitoring stop`；不要在日常操作中使用 `down -v`。API 和数据库的故障恢复以及监控数据保留证据见 `../STAGE4_SUMMARY.md`。

## 自动化测试

```powershell
./evals/check.ps1
```

脚本挂载当前源码和测试，复用镜像内依赖，禁用外部网络且不传入 `.env`；它同时执行接口回归与评分器/负载统计测试，避免只测试旧镜像代码。测试通过后仍需实际 HTTP、数据库、监控和线上追踪验收。自动化测试使用可控替身注入供应商超时、鉴权错误和异常输出，避免依赖供应商恰好故障。
