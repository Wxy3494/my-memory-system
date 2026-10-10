# 本次修改清单与检查入口

日期：2026-10-06。当前工作项目：比赛目录中的 `ai-customer-service-rag`。本次实际修改仅在此项目内，原上层两份方案保留供核对。

## 交付状态

后续本地配置与真实验收：我的模型与本地运行配置已填写，模型 probe、真实 Add/Search 小样、API 容器重启后直接检索均通过；两份报告已复制并核对。见 [真实运行记录](evidence/20261006-memory-live/acceptance.md)。当前下一步为确认服务器/域名/预算并准备公网部署；正式检索质量与平台评测尚未运行。

V0 代码、迁移、鉴权、独立部署、100 题诊断集、评测/负载脚本已实现。72 项测试中 71 通过、1 个真实付费模型场景跳过；真实 PostgreSQL/pgvector 的事务、并发、隔离、Top100 和容器重启持久化已验证。真实模型闭环、公网、平台 Smoke/Full 仍需补充外部依赖，尚不是有效参赛提交。

## 对现有文件的修改

| 文件 | 修改内容 | 检查重点 |
|---|---|---|
| app/main.py | 导入并注册 memory router 和仅作用于记忆路径的请求体上限中间件 | 原 /ask、/v1/retrieve 业务代码未重写；仍分别走原路由 |
| app/observability.py | 将赛事路径加入固定指标白名单；新增记忆请求的状态/耗时日志 | 不记录正文、用户 ID、源 request_id、令牌；原客服追踪仍仅用于旧路由 |
| requirements.txt | 补充直接使用的 httpx==0.28.1 | 原生成/FAQ 模型依赖仍保留 |
| .gitignore / .dockerignore | 忽略真实 .env.*、测试依赖/临时目录、本地结果；保留配置模板 | Key 不进入镜像和后续提交 |
| README.md | 新增参赛主入口、交付状态和检查链接 | 下方原客服历史说明保留；历史数字不能当记忆成绩 |

## 新增文件及职责

| 文件/目录 | 实现内容 |
|---|---|
| app/memory/config.py、schemas.py、errors.py | 独立配置、模型/维度与 pipeline 签名、严格契约、脱敏错误码 |
| app/memory/chunking.py | 全文覆盖、Unicode 偏移、稳定 ID、完整有效载荷哈希 |
| app/memory/embeddings.py | HTTPS 模型调用、10 条分批、index 重排、数值验证、有界重试、tokens 计量和近期探测缓存 |
| app/memory/store.py | 用户范围 SQL、事务、请求锁、幂等、来源和持久化检索 |
| app/memory/service.py、retrieval.py | Add/Search 编排、角色/时间前缀、证据返回；可选中文词项+RRF |
| app/memory/routes.py、limits.py | Bearer 鉴权、HTTP 错误、就绪和请求体限制 |
| app/memory_main.py | 赛事独立应用，不导入旧 FAQ/BGE/DeepSeek 依赖 |
| migrations/001_memory.sql | 独立 schema、四张业务表+版本表、复合外键和索引 |
| Dockerfile.memory、Dockerfile.memory-offline、compose.memory.yaml、deploy/Caddyfile | 单独镜像、离线构建选项、新数据库持久化卷、显式迁移任务、可选公网 HTTPS |
| requirements-memory.txt / .lock.txt、.env.memory.example | 轻量运行依赖、约束版本、无秘密的配置模板 |
| scripts/memory_admin.py | 明确迁移、付费小样模型探测、指定用户清理 |
| scripts/memory_smoke.py | 自建真实 HTTP 验收及服务重启后再检索入口；不代替平台 Smoke |
| scripts/verify_memory.py、verify_memory_launch.py | 离线回归+语法/哈希记录；真实无密钥进程启动检查 |
| tests/test_memory_contract.py、test_memory_config.py、test_memory_evaluation.py | 协议、隔离、幂等、异常、长文、配置、隐私和评分验证 |
| tests/test_memory_integration.py | 7 个真实 DB 用例已通过，1 个真实付费模型用例跳过 |
| evals/build_memory_cases.py、memory_cases_dev.jsonl、memory_cases_holdout.jsonl | 可复建的 60/40 合成诊断集，按用户/会话隔离 |
| evals/memory_eval.py、memory_load.py | 来源/quote 审计、证据 Recall、完整覆盖、错误、延迟、容量小样 |
| docs/memory-*.md、competition-submission.md | 设计、部署、评测、修改清单、用户补充项、提交模板 |
| docs/evidence/20261006-memory/ | 当前测试文本、JSON 汇总、API 启动检查及源码哈希 |

## 建议检查顺序

1. 看 `memory-user-inputs.md`：查看运行所需的外部依赖。
2. 看 `memory-design.md` 的请求/返回和处理顺序，再对照 routes → service → store。
3. 对照迁移表、唯一约束、user_id 过滤 SQL 和事务提交的位置。
4. 打开 `docs/evidence/20261006-memory/unit-tests.txt` 与 verification.json，查看通过与跳过，不把 skip 当 pass。
5. 配置真实模型/数据库，按 `memory-deployment.md` 跑自建闭环、重启和独立外网检查。
6. 跑固定 100 题及容量记录，再填写 competition-submission.md，申请官方 Smoke/Full。

## 方案映射及未实现部分

| 原计划 | 当前状态 |
|---|---|
| M0 设计、旧项目检查 | 已有设计、旧回归、代码哈希；真实模型、费用及组别核实待补 |
| M1 接口与表 | 已实现；协议、SQL 语法和真实 DB 迁移/重复迁移已验证 |
| M2/M3 可靠 Add、隔离 Search | 真实 DB 事务、并发、立即可见、隔离、Top100 及 DB 容器重启已验证；真实模型待补 |
| M4 评测/部署 | 轻量镜像构建、依赖检查、Compose 迁移/API 启动已通过；真实 Recall、容量和公网待补 |
| M5/M7 申请、平台 Smoke、Full、复核 | 模板已创建；需服务器、仓库、身份和 Eval Key |
| M6 可选改进 | 实验 hybrid 已实现但未证明收益，默认 vector；相邻窗口和事实层未实现 |

V2、前端、复杂多 Agent 等并非当前 V0 交付要求。没有创建付费云主机、公开仓库或正式提交，也没有修改真实密钥。Git 副本当前没有初始提交，所有文件均未跟踪，所以不能用 git diff 原有基线代替此清单；后续先确认署名/公开范围，再建立正式版本。

## Docker 当前结果

已构建 `tracememory:v0`，Linux Python 3.13.15，镜像约 102 MB，非 root 用户 memory，未安装 sentence-transformers。标准在线构建遇到容器 DNS 错误，离线同版本 wheels 构建及 pip check 成功。

实际使用独立项目 `tracememory-qa-smoke` 和回环端口 18061 跑通 db → migrate(exit 0) → api(healthy)；health=200、OpenAPI=200、错 Token=401、非法 top_k=422。就绪检查确认数据库/迁移正常，上游未探测所以返回 503，符合当前未补模型的状态。测试配置均为合成值，未读取旧 .env。

完成后已清理本次测试容器/测试卷，保留镜像和离线 wheels；原客服、Prometheus、Grafana 与原数据库容器仍运行。当前没有用合成配置冒充正式部署。镜像哈希和详细状态在 docker.json。
