# 我的记忆系统：CSIG 文本记忆参赛项目（内部名称 TraceMemory，含原客服 RAG）

2026-10-06，在现有项目中新增独立对话记忆模块。V0 代码、真实 PostgreSQL/pgvector 集成测试、真实模型 Add/Search、API 重启、自建 100 题检索诊断和同用户 1000 条串行样本已完成。来源审计修复后，已保存的 100 题原始结果通过免费本地复查。公网 HTTPS、最终服务器容量和平台 Smoke/Full 尚未完成，项目尚未提交。用户已授权发布 GitHub 公开仓库并选择 MIT 许可证；公开准备与云端进展见 [发布状态](docs/publication-status.md)。

参赛实现位于本仓库根目录。使用下列独立记忆服务入口复现；原客服项目说明作为历史背景保留。

- [修改清单与逐项检查入口](docs/memory-change-summary.md)
- [最后需要补充的接口、服务器和申请信息](docs/memory-user-inputs.md)
- [赛事接口与设计](docs/memory-design.md)
- [部署和真实验收命令](docs/memory-deployment.md)
- [100 题数据、评测与验证范围](docs/memory-evaluation.md)
- [提交材料模板](docs/competition-submission.md)
- [本地收尾与尚未完成事项](docs/local-release-status.md)
- [来源与许可状态](NOTICE.md)
- [评测数据保留、备份与清理流程](docs/memory-data-operations.md)

赛事入口：`app.memory_main:app`，依赖 `requirements-memory.txt`，部署用 `compose.memory.yaml`，配置用 `.env.memory.example`。Add/Search 也已注册到原应用 `app.main:app`。赛事模块仅返回证据，不调用 DeepSeek、BGE 或模拟订单查询。

以下为原客服项目说明及历史证据。历史客服成绩不代表本次记忆模块成绩。

## 原客服 RAG 项目

一个模拟电商客服项目，使用 FastAPI 提供问答接口。

个人订单、退款问题查询模拟记录；通用店铺规则通过本地向量检索获取证据，再调用 DeepSeek 组织回答。证据不足时提示联系人工客服。

订单、退款和店铺规则均为教学用模拟数据，未连接真实业务系统。

## 2026-10-03 检查补充

新增 `POST /v1/retrieve`：复用业务优先路由，返回 FAQ 候选及版本信息，不调用 DeepSeek。补充检索专用指标、看板和回归/负载入口。契约和命令见 [纯检索说明](docs/retrieval-api.md)，本次检查与验证范围见 [项目检查总结](docs/project-review-20261003.md)。已有 `/ask` 四字段契约保持不变，历史实测仅对应记录中的源码/镜像版本。

## 求职证据与演示入口

2026-10-03，Codex 经授权辅助完成真实请求实测，原始结果可复算：

- [实测报告](docs/career-evidence-report.md)：固定 46 题自动检查 46/46；30 题检索 Hit@1 为 28/30、Recall@3 为 100%。自动检查不等于语义准确率。
- [逐题复核](docs/evidence/20261003-career-run/answer-review.md)：保留历史两处路由错误、三处条件省略风险及本轮两条补充偏多的回答。
- [负载原始结果](docs/evidence/20261003-career-run/raw.json)：重复与新问法在并发 1、2 下各组 20 请求，共 80 个完整 RAG 样本通过路由及引用检查。热模型、容器回环、小样本，不代表生产容量。
- [简历数字及来源](docs/resume-evidence.md)、[五分钟演示稿](docs/five-minute-demo.md)：只使用已有证据，独立讲解能力尚未验收。

已部署后，在项目根目录运行 `./evals/career_run.ps1 -RunName <新的结果名>` 可重跑；用 `python ./evals/career_report.py ./docs/evidence/<结果名>` 汇总，用 `python ./evals/verify_career.py ./docs/evidence/<结果名>` 复算验证。重跑调用真实生成服务；首次配置和部署见下文。

## 当前功能

- 按订单号查询模拟订单状态。
- 按退款单号查询模拟退款状态。
- 个人查询缺少单号时，提示补充。
- 查不到记录时如实说明，并提示联系人工。
- 从 Markdown FAQ 中解析规则，保留规则 ID、行号和版本。
- 使用本地 BGE 模型生成 512 维向量。
- 使用 PostgreSQL 和 pgvector 存储、检索 FAQ。
- 根据内容哈希复用未变化的向量，更新变化的内容。
- 调用 DeepSeek 根据检索证据回答，并返回引用来源。
- 校验模型返回的 JSON，以及引用 ID 是否来自本次检索结果。

`handoff` 表示提示用户联系人工，项目尚未创建真实人工工单。

## 技术组成

| 用途 | 技术 |
| --- | --- |
| HTTP 接口 | FastAPI |
| 输入和模型输出校验 | Pydantic |
| FAQ 向量模型 | BAAI/bge-small-zh-v1.5，本地 CPU 运行 |
| 向量存储 | PostgreSQL + pgvector |
| 数据库访问 | psycopg |
| 答案生成 | DeepSeek，通过 OpenAI Python SDK 调用 |
| 本地配置 | .env + python-dotenv |

## 文件结构

```text
ai-customer-service-rag/
├── app/
│   ├── main.py          # 接口、问题分流、模拟记录查询
│   ├── mock_data.py     # 模拟订单和退款
│   ├── faq_loader.py    # FAQ 解析及来源信息
│   ├── faq_search.py    # 本地模型加载和向量检索
│   ├── faq_answer.py    # DeepSeek 回答、引用校验及失败处理
│   ├── readiness.py     # 本地依赖就绪检查
│   ├── observability.py # 请求编号、日志和指标
│   └── tracing.py       # 脱敏追踪与后台导出
├── docs/
│   ├── faq.md           # 模拟店铺规则
│   └── compose-acceptance.md # Compose 验收记录
├── index_faq.py         # FAQ 入库和增量更新
├── tests/               # 接口、路由、检索和监控回归
├── evals/               # 固定集、评分器、纯检索负载与统一测试入口
├── monitoring/          # Prometheus 告警与 Grafana 配置
├── requirements.txt    # Windows 和 Linux 的直接依赖
├── requirements-linux.lock.txt # Linux CPU 完整版本约束
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── .gitignore
├── .env.example         # 不含真实凭据的配置模板
├── .env                 # 本机配置，Git 忽略
└── README.md
```

## 配置

首次配置时，参考项目根目录的 `.env.example` 创建 `.env`，再填写实际值。已有 `.env` 时逐项核对，保留原有配置。

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-flash
DATABASE_URL=postgresql://rag:replace_with_local_password@127.0.0.1:5432/ragdb
HF_HUB_CACHE=./.cache/huggingface/hub
```

上述 Key 留空、密码为占位符；使用前需填写实际值，并核对数据库用户名、端口和数据库名。

| 配置 | 用途 | 读取位置 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | FAQ 生成需要；纯检索与模拟业务查询可留空 | `app/faq_answer.py` |
| `DEEPSEEK_MODEL` | DeepSeek 生成模型名称，代码默认 `deepseek-flash` | `app/faq_answer.py` |
| `DATABASE_URL` | FAQ 入库和检索的数据库连接串 | `index_faq.py`、`app/faq_search.py` |
| `DATABASE_URL_DOCKER` | 容器专用连接串，主机为 `db`；注入容器的 `DATABASE_URL` | `compose.yaml` |
| `HF_HUB_CACHE` | 本地 BGE 模型缓存目录，入库和检索需要 | `index_faq.py`、`app/faq_search.py` |
| `POSTGRES_PASSWORD` | Compose 数据库配置，填写现有账号密码；已有数据目录不会因此重置密码 | `compose.yaml` |

代码从进程环境变量读取配置。当前入库、检索命令通过 `dotenv run` 加载 `.env`，API 启动命令通过 `--env-file .env` 加载；`.env.example` 本身不会被自动加载。

`.env` 已加入 `.gitignore`。不要公开真实 Key。
修改配置后需要重启服务。

### 宿主机与容器中的地址、路径

以下容器设置已写入第四阶段步骤 2 的 Compose 配置；数据库切换、API 启动、容器内模型检索和三个 HTTP 样例已验证，具体证据见下方部署记录。

| 项目 | Windows 方式 | Compose 配置中的容器方式 |
| --- | --- | --- |
| 数据库地址 | 示例为 `127.0.0.1:5432`，通过宿主机发布端口访问 | 同一 Compose 网络内使用数据库服务名，例如 `db:5432` |
| 模型缓存 | `./.cache/huggingface/hub` | 将宿主机目录挂载到例如 `/models/hub`，设置 `HF_HUB_CACHE=/models/hub` |
| API 监听地址 | `127.0.0.1:8000` | 容器内需监听 `0.0.0.0:8000`，再配置宿主机端口映射 |

`127.0.0.1` 指向程序所在的网络环境。API 在容器里时，它指向 API 容器自身；访问另一个数据库服务需要使用该服务的名字。容器内访问模型文件时也要使用挂载后的容器路径。

Compose 所需的新增变量见 `.env.example`。在实际 `.env` 中新增 `DATABASE_URL_DOCKER`：复制原 `DATABASE_URL` 的值，只把主机 `127.0.0.1` 改为 `db`，保留用户名、密码编码、端口和数据库名。原 `DATABASE_URL` 继续供 Windows 命令使用。`HF_HUB_CACHE` 继续填写宿主机缓存目录，Compose 将其只读挂载到 `/models/hub`，并将 API 容器的 `HF_HUB_CACHE` 设置为该容器路径。配置后可用 `docker compose config --quiet` 检查解析；不要公开解析后的配置内容。

### Compose 构建、初始化与日常启动

在项目根目录的 PowerShell 中执行；先启动 Docker Desktop。

```powershell
$stage4Docker = 'docker.exe'
& $stage4Docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose 配置检查失败' }
& $stage4Docker compose build api
if ($LASTEXITCODE -ne 0) { throw '镜像构建失败' }
& $stage4Docker compose up -d --no-build --wait --wait-timeout 60 db
if ($LASTEXITCODE -ne 0) { throw '数据库启动失败' }
& $stage4Docker compose run --rm --no-deps index
if ($LASTEXITCODE -ne 0) { throw 'FAQ 入库失败' }
& $stage4Docker compose up -d --no-build --wait --wait-timeout 60 api
if ($LASTEXITCODE -ne 0) { throw 'API 启动失败' }
& $stage4Docker compose ps
```

当前环境复用外部卷 `rag_pgdata`，必须保持旧 `rag-pgvector` 停止，避免两个 PostgreSQL 实例使用同一数据目录。`POSTGRES_PASSWORD` 只影响空数据目录的初始化，不会重置已有数据库账号的密码。

数据库镜像采用 `pull_policy: never`，需要本机已有 `pgvector/pgvector:pg17`；新电脑先显式拉取该标签并核对版本。在真正的新环境中，确认没有同名旧卷需要保留，再执行 `docker volume create rag_pgdata`，按上述顺序启动数据库、独立入库和 API。Compose 的数据库入口会在空卷中创建配置的账号和数据库；`index_faq.py` 在目标数据库启用 `vector` 扩展、创建表，再同步 FAQ。这些 SQL 和数据写入处于同一事务；数据库必须包含 pgvector 支持文件，初始化账号须有创建扩展的权限。

宿主机模型缓存目录必须预先存在，例如 `New-Item -ItemType Directory -Force '.\.cache\huggingface\hub'`。缓存为空时，首次独立入库需要网络下载模型；下载完成后 API 从本地缓存加载，缓存不可用时不会自动联网下载。此次空数据库验收使用已有模型缓存，未覆盖空缓存首次联网下载。

日常启动已有部署：`docker compose up -d --no-build --wait --wait-timeout 60 db api`。API 启动只启动 HTTP 服务，不执行入库；普通 `up` 不会运行 `tools` profile 的 `index` 任务。API 健康检查调用 `/health`，仅表示进程存活，不保证数据库、模型和 DeepSeek 全部可用。

### Compose 独立入库与 FAQ 更新

修改 `docs/faq.md` 并更新版本后，运行 `docker compose run --rm --no-deps index`，再核对检索和接口回答。数据库需先就绪；`--no-deps` 不启动依赖服务，`--rm` 清理本次任务容器。该任务只接收数据库和缓存配置，不调用 DeepSeek。

`index` 只读挂载当前宿主机文档，无需为 FAQ 更新重新构建镜像；模型缓存允许写入以下载或补齐文件，API 的模型缓存保持只读。内容和模型未变化时复用向量，同时更新版本和行号等元数据；内容变化时重算对应向量，文档块删除时删除该来源的对应记录。数据库已保存 FAQ 内容，API 回答使用检索到的数据库内容。

修改 Python 代码、`Dockerfile` 或依赖文件时，先执行 `docker compose build api`，再执行 `docker compose up -d --no-build --force-recreate --wait --wait-timeout 60 db api`。构建本身不会替换运行中的 API。API 与独立入库共用镜像，新增依赖后应在目标 Linux CPU 环境重新导出并检查版本约束。

`requirements.txt` 固定直接依赖，`requirements-linux.lock.txt` 固定已验证的 Linux / Python 3.13 / CPU 环境全部 58 个已安装包版本，构建时作为 pip constraints 使用；PyTorch CPU 包通过官方 CPU 索引安装。该文件不适用于 Windows，不包含安装包哈希，也没有锁定基础镜像摘要，因此不声称字节级重现或完全离线构建。[pip 版本固定说明](https://pip.pypa.io/en/stable/topics/repeatable-installs/)

## 当前 Windows 环境的启动方法

以下命令在项目根目录的 PowerShell 中运行。
当前环境已创建 `.venv`、数据库容器和模型缓存。

数据库已切换到 Compose，下面统一启动 Compose 的 db，并保持旧 `rag-pgvector` 停止，避免两个数据库实例同时使用 `rag_pgdata`。Windows 虚拟环境安装依赖后仍可连接宿主机发布的数据库端口。

### 1. 首次准备或依赖变更时安装依赖

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 启动数据库

先打开 Docker Desktop，等待引擎运行，然后启动 Compose 数据库：

```powershell
$docker = 'docker.exe'
& $docker compose up -d --no-build --wait --wait-timeout 60 db
```

容器启动后需要等待 PostgreSQL 就绪：

```powershell
& $docker compose exec -T db pg_isready -U rag -d ragdb
```

出现 `accepting connections` 后再执行索引或检索。

当前数据库已启用 vector 扩展，数据保存在 `rag_pgdata` 卷中。

### 3. FAQ 首次入库或修改后更新

```powershell
.\.venv\Scripts\python.exe -m dotenv run -- .\.venv\Scripts\python.exe index_faq.py
```

未变化的内容会复用向量。日常启动接口不需要重复入库。
FAQ 修改后应更新文档版本，并重新运行索引脚本。

首次需要计算向量且模型缓存为空时，索引脚本会下载模型。
接口检索只读取本地模型文件。

### 4. 启动接口

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000
```

接口文档：http://127.0.0.1:8000/docs

按 Ctrl+C 停止接口服务。

### 单独核对本地检索

数据库就绪、FAQ 已入库、模型缓存可用时，可以独立检查检索，不调用 DeepSeek：

```powershell
.\.venv\Scripts\python.exe -m dotenv run -- .\.venv\Scripts\python.exe -m app.faq_search "付款后一般多久发货？"
```

输出规则 ID、相似度、来源行号、版本和内容。该命令用于检查本地模型和宿主机到数据库的检索链路。

## 接口

### GET /health

返回：

```json
{"status": "ok"}
```

这是接口进程的健康检查，不代表数据库或模型服务可用。

### POST /ask

输入：

- `question`：必填，不能为空或仅有空白。
- `order_id`：查询订单时提供。
- `refund_id`：查询退款时提供。

订单查询示例：

```json
{
  "question": "我的订单发货了吗？",
  "order_id": "ORD-1001"
}
```

通用规则示例：

```json
{
  "question": "付完款通常几天能寄出？"
}
```

输出字段：

| 字段 | 含义 |
| --- | --- |
| answer | 给用户看的回答 |
| route | order_lookup、refund_lookup、faq_rag 或 handoff |
| sources | 本次回答使用的记录或 FAQ 来源 |
| needs_human | 是否提示人工继续处理 |

缺少个人查询单号时，返回补充单号的提示，来源为空。

通用规则回答会返回规则 ID、文件行号和文档版本，例如：

```text
RULE-SHIPPING-01 | docs/faq.md:19-23 | 版本=2026-09-30-v3
```

## 已验证结果

2026-09-30，通过 Swagger 手动测试：

| 场景 | 结果 |
| --- | --- |
| 通用发货规则 | 根据 FAQ 回答，保留限制条件并引用来源 |
| 订机票等无依据问题 | 提示联系人工，引用为空 |
| ORD-1001 订单查询 | 返回已发货及模拟订单来源 |
| 个人订单问题缺少单号 | 提示补充订单号 |
| REF-2002 退款查询 | 返回已退款及模拟退款来源 |
| ORD-9999 不存在的订单 | 明确未查到，提示联系人工 |

此前已验证 FAQ 入库、重复运行复用向量，以及修改 FAQ 后检索到更新内容。

这些结果证明对应样例通过，不代表所有问题都能正确处理。

### 第四阶段步骤 1：2026-10-01 环境核对

以下运行证据来自用户在项目根目录手动执行命令后提交的终端截图，由导师核对；配置模板和依赖文件由导师辅助编写。

| 核对项 | 本次结果 |
| --- | --- |
| Python | 项目虚拟环境为 `3.13.12` |
| 直接依赖 | 八个直接依赖已按当前安装版本固定在 `requirements.txt` |
| 数据库容器和镜像 | `rag-pgvector`，镜像 `pgvector/pgvector:pg17` |
| 数据库实际版本 | `SHOW server_version` 返回 `17.11 (Debian 17.11-1.pgdg12+2)` |
| 数据库就绪 | 容器启动后，容器内 SQL 查询成功 |
| 数据库存储 | `rag_pgdata` 命名卷，挂载到 `/var/lib/postgresql/data` |
| 数据库向量扩展 | `vector` 扩展版本 `0.8.6`；Python `pgvector` 包版本为 `0.5.0` |
| 已入库 FAQ | `docs/faq.md`，版本 `2026-09-30-v3`，共 `14` 条 |
| 本地模型 | 缓存 `./.cache/huggingface/hub`，本地加载成功，设备 `cpu`，模型维度 `512` |
| Windows 检索链路 | 问题“付款后一般多久发货？”检索成功；首条 `RULE-SHIPPING-01`，相似度 `0.7544`，行号 `19-23`，版本 `2026-09-30-v3` |

以上是步骤 1 当时的核对范围；Compose、Linux 依赖和数据保留已在步骤 2 验收，性能指标尚未测试。

已有数据卷的复用方案已在步骤 2 落实。以 PostgreSQL 17 为基线，切换前准备备份，并确保原数据库实例停止后再让新的实例使用该数据目录；不删除现有卷。14 条和版本号是当前数量与版本基线，步骤 2 已进一步保存并比较 FAQ ID、内容、向量摘要和全部元数据，验收重建后的数据一致性。

### 第四阶段步骤 2：2026-10-01 Compose 部署验收通过

用户先完成部分手动操作，随后授权 Codex 直接执行剩余验收。本次属于辅助完成；完整结果和证据路径见 [Compose 验收记录](docs/compose-acceptance.md)。

| 验收项 | 实际结果 |
| --- | --- |
| 配置、镜像和依赖 | Compose 配置解析成功；新版镜像构建成功；CPU PyTorch、Linux 导入与 pip check 通过；58 个包与完整版本约束逐项一致 |
| 全新数据库 | 临时空卷启动数据库，独立入库自动启用 vector、建表，写入 14 条 FAQ |
| 启动与入库分离 | 普通 up 只运行 api、db；API 启动后空库仍为空，index 按需单独运行 |
| 增量入库 | 首次重算 14；重复复用 14；单条修改重算 1、复用 13；删除规则后剩 13、删除 1；恢复文档后内容和元数据正确 |
| 备份实际恢复 | 现有本机归档在临时数据库实际恢复，14 条内容、向量摘要及全部元数据与正式基线一致 |
| 容器重建与持久化 | db、api 容器 ID 均改变；原外部卷继续使用，14 条记录的内容、向量摘要和全部元数据完全一致 |
| 模型缓存 | 新 API 容器使用原只读缓存，本地 CPU 检索成功，首条 RULE-SHIPPING-01 |
| HTTP 样例 | 宿主机 /health、订单、退款、缺少单号、未知订单、发货 FAQ、无依据地址问题全部符合预期 |
| 最终状态与清理 | 正式 api、db 均 healthy；原 rag-pgvector 保持停止；临时验收容器、网络和卷已清理 |

原始证据保存于 `.cache/acceptance/20261001-compose/`，旧备份和切换前 CSV 继续保留。健康检查仍仅验证进程存活；上述结论不包括空模型缓存首次联网下载、完全离线构建、故障演练和性能验收。

## 当前限制与待验证项

- 问题分流使用关键词，可能误判复杂表达。
- 单号需通过独立字段提供，尚未从问题文本中自动提取。
- 同时询问多个事项时，尚未实现完整的组合回答。
- 引用 ID 校验不能保证回答的每句话都受到证据支持。
- 无真实业务系统、用户鉴权和人工工单系统。
- 数据库、模型缓存缺失和空 FAQ 已做实际故障与恢复验证；供应商超时、鉴权错误和异常输出已做受控测试注入，见第四阶段记录。
- 已完成 46 题固定集及并发 1/2 的小规模性能基线；仍未进行大规模评估、长时间压测或生产容量验证，见第五阶段总结。

### 第四阶段步骤 3–7：监控、追踪与故障恢复

2026-10-02，用户授权 Codex 辅助完成就绪检查、请求编号与 JSON 日志、Prometheus、Grafana、LangSmith 脱敏追踪和故障恢复验收。17 项自动化测试通过；云端父子追踪实际可查询；数据库、模型、空 FAQ 和监控故障行为已验证，正式 FAQ 完整快照保持一致。

完整验收结果见 [第四阶段总结](STAGE4_SUMMARY.md)，启动及排障说明见 [运行与排障](docs/observability.md)。Grafana 仪表盘位于 http://127.0.0.1:3000/d/rag-stage4 。

```powershell
docker compose --profile monitoring up -d --build --wait --wait-timeout 120 db api prometheus grafana
```

本阶段新增 `prometheus-client==0.26.0`，当前九个直接依赖及 Linux 完整版本约束一并固定。`/health` 仍只验证进程存活，`/ready` 用于本地依赖就绪；业务结果需查看 `route`、`needs_human` 和技术失败指标。第五阶段的固定题集和小规模性能结果见下方。

## 第五阶段：固定题集与性能基线

2026-10-02 辅助完成：初始固定集 44/46 通过；2026-10-03 修复两处关键词分流缺陷后，自动检查 46/46、新增问法 8/8 通过。生成答案仍有条件省略待改进，不能视为语义全部通过。小规模性能样本全部业务成功，但不代表容量上限。详见 [第五阶段总结](STAGE5_SUMMARY.md) 和 [复现说明](evals/README.md)。


分流修复、回归结果及语义复核限制见 [修复验收](docs/routing-regression.md)。
