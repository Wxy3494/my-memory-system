# 赛事 Python 依赖来源记录

2026-10-06：从已用于离线构建的 Linux wheel 读取元数据；范围为 requirements-memory.txt 和 requirements-memory.lock.txt，不是整个旧客服环境或操作系统的许可清单。发行包所带原始许可文本具有优先性，版本和镜像应在正式部署时再次核对。

| 包 | wheel 版本 | 元数据声明的许可 |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| fastapi | 0.141.1 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| numpy | 2.3.5 | See package bundled license text |
| pgvector | 0.5.0 | MIT |
| prometheus_client | 0.26.0 | Apache-2.0 AND BSD-2-Clause |
| psycopg | 3.3.6 | LGPL-3.0-only |
| psycopg-binary | 3.3.6 | LGPL-3.0-only |
| pydantic | 2.13.5 | MIT |
| pydantic_core | 2.46.5 | MIT |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| starlette | 1.7.0 | BSD-3-Clause |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.5 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |

完整项目链接、wheel 哈希和许可文件名保存在 `evidence/20261006-memory-local-closeout/dependency-metadata.json`。本地源码包不打包第三方 wheel；Linux 镜像安装的依赖保留各发行包附带的许可。Python、Debian、PostgreSQL/pgvector、Caddy 镜像的系统组件另外适用各自许可，本表不覆盖它们。

整体项目开源许可尚未选择。元数据整理不构成已经完成全部来源或许可审查的声明。
