# Compose 部署验收记录

验收结论：第四阶段步骤 2 的 Compose 部署范围通过。执行方式为用户授权后由 Codex 辅助完成，不计作用户独立编码验收。对应样例成功不代表生产环境全面验收。

完成时间：2026-10-01 19:34:10 +08:00。

正式项目始终位于 `.`。本次不读取或保存实际 `.env` 凭据，Compose 在运行时读取项目配置。

## 本次完善

- 新增 `requirements-linux.lock.txt`，固定 Linux / Python 3.13 / CPU 环境的 58 个已安装包版本，Dockerfile 构建时同时使用直接依赖与完整版本约束。
- 构建并运行包含空库扩展初始化的 `index_faq.py`：先启用 vector，再注册类型、建表和同步 FAQ。
- README 补充构建、全新数据库初始化、独立入库、FAQ 更新及日常启动说明。

## 正式环境

| 项目 | 实测结果 |
| --- | --- |
| Compose | 5.4.0，项目 `rag-stage4` |
| API | `rag-stage4-api-1`，running / healthy，`127.0.0.1:8000` |
| PostgreSQL | `rag-stage4-db-1`，running / healthy，`127.0.0.1:5432` |
| 数据库实际版本 | PostgreSQL 17.11，vector 扩展 0.8.6 |
| Python / PyTorch | 3.13.15 / 2.14.0+cpu，CUDA 构建为 null |
| 完整依赖核对 | 实际安装的 58 个包与版本约束逐项一致；pip check 通过 |
| 持久化 | 原外部卷 `rag_pgdata` 继续挂载到 `/var/lib/postgresql/data` |
| 模型缓存 | 原宿主机目录挂载到 `/models/hub`，API 挂载 RW=false，CPU 本地加载成功 |
| 原数据库容器 | `rag-pgvector` 保持 exited，重启策略 no |
| 原始 FAQ | 14 条，版本 2026-09-30-v3；正式文档没有修改 |

本次 API 镜像 ID：`sha256:ab22fa859a187ea728b5941a4e9974fe704fd58cd924fc26d4ffd2da82690a9e`。这是验收时的镜像身份记录；Compose 仍使用本地标签，基础镜像和安装包未做摘要/哈希锁定。

## 空库初始化与独立同步

测试使用临时项目 `rag-stage4-acceptance-20261001` 和全新卷 `rag_stage4_acceptance_20261001`，与原卷分开；临时数据库不发布宿主机端口，API 使用本地 18000 端口。FAQ 改动只发生在 `.cache/acceptance/20261001-compose/docs/faq.md` 的副本。

| 场景 | 实测结果 |
| --- | --- |
| 全新 PostgreSQL 卷 | 入口成功创建 rag 账号和 ragdb 数据库，检查时没有 vector 扩展或 FAQ 表 |
| 普通 up 启动 API | 仅 api、db 两个常驻服务；启动后扩展和 FAQ 表仍不存在，确认 API 启动不执行入库 |
| 第一次独立入库 | 自动启用 vector 0.8.6、创建表：总数 14、重算 14、复用 0、删除 0 |
| 重复入库 | 总数 14、重算 0、复用 14、删除 0；包括向量摘要在内的完整快照一致 |
| 修改一条内容并更新文档版本 | 发货规则从 2 改为 3 个工作日：重算 1、复用 13；全部版本元数据更新，其他 13 条内容和向量保持一致 |
| 删除最后一条规则 | 删除 RULE-STOCK-01：总数 13、重算 0、复用 13、删除 1，保留条目的完整快照一致 |
| 恢复原文档 | 总数 14、重算 2、复用 12、删除 0；内容和全部元数据恢复，512 维向量数值校验通过 |
| 临时库本地检索 | 返回 3 条，首条 RULE-SHIPPING-01，原版本和内容正确 |

所有独立入库任务退出码均为 0。临时入库设置 `HF_HUB_OFFLINE=1`，使用已有模型缓存；API 通过 `local_files_only=True` 使用本地缓存。

恢复文档后，两个重算向量的 MD5 与最初大批次计算的值不同。逐元素检查最大绝对差为 `8.940696716308594e-08`，通过 `rtol=1e-5`、`atol=1e-6`；不能将重新计算后的字节摘要完全相同作为验收条件。未修改条目的向量和正式数据库持久化比较仍要求摘要完全一致。

## 原数据保留与备份恢复

- 保存正式环境完整基线，包括 source、chunk_id、chunk_no、version、start_line、end_line、content_md5、content_hash、model_name 和 vector_md5（向量文本摘要）。
- db、api 强制重新创建，两个容器 ID 均改变；使用原卷，14 条记录上述字段逐项完全一致。
- 在正式环境再运行独立 index：14 条向量全部复用，完整快照不变。
- 本地检索成功，首条发货规则及来源版本正确，证明新 API 容器仍可使用原缓存和数据库。
- 将现有 41,719 字节备份 `ragdb-before-compose-20261001-181521.dump` 复制进临时数据库容器，在独立的 ragrestore 数据库实际执行 `pg_restore --no-owner --exit-on-error`，退出码 0；恢复后 14 条内容、向量摘要及全部元数据与正式基线完全一致。
- 验收完成后移除临时项目容器、网络和专用测试卷，原 rag_pgdata 与备份文件保留；清理后再次比较正式数据，仍完全一致。

## 宿主机 HTTP 验收

通过 Windows 宿主机的 `http://127.0.0.1:8000` 访问实际部署，共测试一个健康请求和六个问答请求；只有下面两个通用问题调用 DeepSeek。

| 请求 | 实测结果 |
| --- | --- |
| GET /health | HTTP 200，status=ok，仅验收存活 |
| ORD-1001 订单查询 | HTTP 200，order_lookup，已发货，needs_human=false，来源含该订单号 |
| REF-2002 退款查询 | HTTP 200，refund_lookup，已退款，needs_human=false |
| 个人订单问题未提供单号 | HTTP 200，order_lookup，要求提供订单号，sources=[] |
| ORD-9999 未知订单 | HTTP 200，handoff，needs_human=true，sources=[] |
| 付款后一般多久发货 | HTTP 200，faq_rag，引用 RULE-SHIPPING-01 / docs/faq.md:19-23 / 2026-09-30-v3；保留现货、2 个工作日、周末/节假日和预售条件 |
| 广州线下门店地址 | HTTP 200，handoff，needs_human=true，sources=[]，明确现有规则不足，不是检索或生成故障的通用提示 |

HTTP 200 的无依据问答仍然是 handoff，不能只看状态码判断答案成功。

## 证据与验收边界

原始证据位于 `.cache/acceptance/20261001-compose/`（Git 忽略）：

- `report.json`：机器可读结果及实际 HTTP 请求/回答。
- `build.txt`、`runtime.json`、`pip-check.txt`：重建镜像、CPU 环境和完整依赖。
- `original-before.json`、`original-after-recreate.json`、`original-after-index.json`、`original-after-cleanup.json`：正式数据完整比较。
- `fresh-snapshot.json`、`changed-snapshot.json`、`deleted-snapshot.json`：临时文档同步结果。
- `backup-restored-snapshot.json`：实际恢复结果。
- `container-ids-before.txt`、`container-ids-after.txt`、`final-services.json`：容器重建和最终状态。
- `source-hashes.json`：验收时应用代码、Compose、Dockerfile、依赖和 FAQ 文件 SHA256。

新环境的空缓存首次联网下载、完全离线构建、服务故障演练、并发/性能、依赖 readiness、指标与链路追踪均未包含在此次验收中。订单和退款继续使用模拟记录，handoff 尚无真实工单系统。

流程参考：[Docker Compose 独立任务](https://docs.docker.com/reference/cli/docker/compose/run/)、[多配置文件覆盖](https://docs.docker.com/reference/compose-file/merge/)、[pip 重复安装与版本固定](https://pip.pypa.io/en/stable/topics/repeatable-installs/)。