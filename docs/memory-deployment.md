# 部署与真实验收

以下是复现与后续部署命令。本次已用用户开启的 Docker 跑通独立 PostgreSQL/pgvector 集成测试及数据库容器重启持久化；最终容器启动证据见 `docs/evidence/20261006-memory/docker.json`。真实模型和公网尚未验收，勿把文档中的全部命令视为已经执行。

## 1. 配置

在本项目根目录复制 `.env.memory.example` 为 `.env.memory`，填写 `docs/memory-user-inputs.md` 列出的值。原 `.env` 不参与赛事部署。

- POSTGRES_PASSWORD 用足够长的随机十六进制/字母数字密码；Compose 直接拼到 DSN，不自动做 URL 编码。
- DATABASE_URL 仅用于宿主机运行；Compose 会覆盖为容器内 db 主机地址。
- MEMORY_EMBEDDING_BASE_URL 填地域/业务空间实际的 HTTPS 兼容接口 base URL，不能写 `/embeddings` 结尾。
- MEMORY_API_KEY 与模型密钥是两份独立值。Full 前固定模型、分块和检索配置。

## 2. Docker 本地启动

需要已经安装且可用的 Docker Engine + Compose。服务器操作系统应为能运行 Linux 容器的环境。

```powershell
docker compose --env-file .env.memory -f compose.memory.yaml config --quiet
docker compose --env-file .env.memory -f compose.memory.yaml up -d --build db migrate api
docker compose --env-file .env.memory -f compose.memory.yaml ps
```

迁移是明确的一次性服务：db 健康后执行，成功后才启动 api；可重复执行并验证签名，不删除旧表。已有部署改代码后需要重建：

```powershell
docker compose --env-file .env.memory -f compose.memory.yaml build api migrate
docker compose --env-file .env.memory -f compose.memory.yaml up -d --force-recreate migrate api
```

不要把配置完整输出发给别人；`config --quiet` 只校验，不显示插值后的密钥。

数据库使用新 `tracememory_memory_pgdata` 卷，未挂载旧 `rag_pgdata`；数据库不开放宿主机端口，API 仅映射回环端口。无 Windows 模型缓存挂载。已有客服服务占用 8000 时，在 `.env.memory` 将 MEMORY_LOCAL_PORT 改为其他值，并同步修改调用的 base URL。MEMORY_ENV_FILE 可显式选择其他配置路径，默认 `.env.memory`。

### 容器无法解析下载域名时

本次 Docker 在线构建因容器 DNS 无法解析 `files.pythonhosted.org` 失败，宿主机网络可下载，因此增加离线构建入口。宿主机先下载同版本 Linux cp313 wheels（不是复制 Windows site-packages）：

```powershell
python -m pip download --dest deploy/wheelhouse --platform manylinux_2_28_x86_64 --platform manylinux_2_27_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 --python-version 3.13 --implementation cp --abi cp313 --only-binary=:all: -r requirements-memory.txt -c requirements-memory.lock.txt
docker build -f Dockerfile.memory-offline -t tracememory:v0 .
```

在 `.env.memory` 增加 `MEMORY_DOCKERFILE=Dockerfile.memory-offline` 后，Compose 同样使用该入口。下载的 wheel 不进 Git，`deploy/wheelhouse/README.md` 保留用途说明。在线环境默认 Dockerfile.memory，无需设置此开关。两种镜像使用同一依赖约束及应用代码。

## 3. 真实模型与 HTTP 闭环

先做两条自建中英文模型探测（会产生模型费用），随后做 API 闭环：

```powershell
docker compose --env-file .env.memory -f compose.memory.yaml exec api python scripts/memory_admin.py probe
docker compose --env-file .env.memory -f compose.memory.yaml exec api python scripts/memory_smoke.py --output /tmp/memory-smoke.json
docker compose --env-file .env.memory -f compose.memory.yaml cp api:/tmp/memory-smoke.json ./evals/results/memory-smoke.json
```

执行 cp 前先创建 `evals/results`。若不在服务器宿主机创建这个目录，可只查看脚本返回的脱敏 JSON。

probe 成功不改变 API 进程的就绪缓存；memory_smoke 的实际 Add/Search 会改变。`/ready/memory` 启动时 503 是预期的未探测状态，健康检查仍使用 `/health`。不要为每个健康检查调用付费模型。

重启后检查持久化（报告先前已保存在容器 /tmp，restart 保留容器文件；重建容器前须保存报告）：

```powershell
docker compose --env-file .env.memory -f compose.memory.yaml restart api
docker compose --env-file .env.memory -f compose.memory.yaml exec api python scripts/memory_smoke.py --check-existing /tmp/memory-smoke.json --output /tmp/memory-restart.json
```

脚本可本机或独立网络调用远程 HTTPS（在本机 Python 环境加载本地密钥，不把 Key 放命令行）：

```powershell
python -m dotenv -f .env.memory run -- python scripts/memory_smoke.py --base-url https://你的域名
```

## 4. 无容器的本机开发与数据库集成

复制进来的旧 `.venv` 可能指向别处的 Python；新建本项目专用环境，不依赖该副本。

```powershell
python -m venv .venv-memory
.\.venv-memory\Scripts\Activate.ps1
python -m pip install -r requirements-memory.txt -c requirements-memory.lock.txt
python -m dotenv -f .env.memory run -- python scripts/memory_admin.py migrate
python -m dotenv -f .env.memory run -- python -m uvicorn app.memory_main:app --host 127.0.0.1 --port 8000 --no-access-log
```

上面要求宿主机已有 PostgreSQL + pgvector，DATABASE_URL 指向它。仅安装轻量依赖后，可运行 memory 专用离线测试：

```powershell
python -m unittest discover -s tests -p "test_memory*.py" -v
python evals/memory_eval.py --validate-only --data evals/memory_cases_dev.jsonl evals/memory_cases_holdout.jsonl
```

全套旧客服测试还需要原 requirements.txt 中的 OpenAI 等依赖；`scripts/verify_memory.py` 会合并运行旧测试与评测测试。pglast/PyYAML 是可选语法检查器，不是线上运行依赖。

真实数据库测试只允许连接**名称以 `_memory_test` 结尾的独立测试库**。例如管理员创建 `tracememory_memory_test`、启用 pgvector 后，在终端本地设置 MEMORY_TEST_DATABASE_URL，然后运行：

```powershell
python -m unittest discover -s tests -p test_memory_integration.py -v
```

该组已在 PostgreSQL 17.11 / pgvector 0.8.6 跑通，用假向量检查数据库事务、并发重复、冲突、增量、来源、级联删除和新连接读取持久化。它不验证真实模型检索质量。真实模型测试需本地 `.env.memory` 已配置，并显式设置 `MEMORY_RUN_LIVE_EMBEDDING=1` 后加载配置运行同一测试。

## 5. 公网 HTTPS

服务器公网可被平台访问、域名 DNS 指向服务器，开放 80/443。填写 MEMORY_PUBLIC_HOST 为域名，无 scheme/path；自动 HTTPS 由 Caddy 申请证书：

```powershell
docker compose --env-file .env.memory -f compose.memory.yaml --profile https up -d edge
```

公开代理仅开放健康、就绪和两个赛事接口；docs/metrics 不对公网开放。Caddy 配置和证书申请尚未实际验证，需服务器启动时确认。基础镜像和 pgvector/Caddy 标签在 Full 前记录实际 digest，最好改用 digest 固定。

## 6. 评测、容量和冻结

```powershell
python -m dotenv -f .env.memory run -- python evals/memory_eval.py --base-url https://你的域名 --data evals/memory_cases_dev.jsonl --label v0-vector --output evals/results/dev-vector.json
python -m dotenv -f .env.memory run -- python evals/memory_load.py --base-url https://你的域名 --messages 100 --concurrency 1
```

memory_eval 需在本机运行，因为镜像不包含 JSONL 数据集；镜像包含评测脚本供自行复制数据后使用。先小样核算费用，然后逐步增至每用户 1千、1万、10万记录；脚本记录的是消息数，实际片段数用数据库查验。服务器另测 RSS、数据库占用、磁盘增长和模型 tokens 配额。不能把离线单元测试耗时作为线上 P95。

正式前记录 Git commit、镜像 digest、源码哈希、模型/维度、分块和检索配置、域名、并发和实测容量。用户已授权继续完成剩余收尾，本地快照通过 Git 保存，包与实际 commit 见 `releases/release-info.json`；用户已授权公开 GitHub 仓库并选择 MIT 许可证；实际链接与固定 Commit 待上传验证。正式部署后需再次冻结一致的代码与镜像。平台 Smoke/Full 由获得的 Eval Key 在官方页面执行，自建 smoke 不代替平台 Smoke。

## 7. 清理与备份

按明确用户 ID 清理自建数据：

```powershell
docker compose --env-file .env.memory -f compose.memory.yaml exec api python scripts/memory_admin.py purge-user --user-id "完整用户ID" --confirm-user-id "完整用户ID"
```

该命令级联删除该用户原文/向量/来源/幂等记录，不删其他用户或 FAQ。清理不可恢复，先核对 ID。Full 运行期间不得清除平台已写数据。平台任务完成后按官方期限清理业务数据以及备份、快照、派生文件和副本；本地输出只用于自己的合成数据。没有启动未经授权的自动清理任务。

备份可通过 `pg_dump` 导出 `memory` schema；恢复必须验证同一 pipeline 签名及计数。本机自建合成库的 dump/独立临时库恢复已完成，五张表计数和全行一致性指纹匹配，见 `evidence/20261006-memory-local-closeout/backup-restore.json`；没有完成恢复后的 HTTP 搜索、服务器故障切换、整机恢复或公网容量验收。正式任务的责任人、30 天期限及全副本清单流程见 `memory-data-operations.md`，目前没有执行正式数据删除。
