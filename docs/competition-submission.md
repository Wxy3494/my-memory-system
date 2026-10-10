# v6 提交说明：部署与原始工作

整理日期：2026-10-10（Asia/Shanghai）。我的项目名称是“我的记忆系统”，内部名称 TraceMemory。我以 Wxy3494 署名，采用 MIT 许可，提供文本记忆服务。[公开仓库](https://github.com/Wxy3494/my-memory-system)。我的提交版本以本说明所属的 Git commit 为准。完整 SHA 和永久链接另存于本地冻结记录。

## 已部署 API 版本

我的部署记录显示，运行容器为 tracememory-api-1，镜像 tracememory:v6-local，镜像 ID `sha256:4cca23e3b81ff8177a54cb2b6c3e1205b549a39d5387f3f540fa3b9225353417`。这是服务器本地镜像 ID，不是公开镜像仓库 digest 或 Git commit。这次源码发布保留了服务器上现有的镜像。源码与原 v6 包的对照见 source-manifest-v6.json。

服务器 /home/admin/my-memory-system 与 /home/admin/my-memory-system-before-v8-20261009-155815 的 app、migrations、环境文件、Compose 与 Dockerfile 比较均一致。我的运行容器配置记录如下，不包含密钥：

| 参数 | 已读取值 |
|---|---|
| Embedding 模型 / 维度 | text-embedding-v4 / 1024 |
| pipeline_version / retrieval | v0 / vector |
| chunk target / overlap | 400 / 60，UTF-8 字节预算 |
| neighbor_window | 0 |
| context_limit / link_hops / signal_scan_limit | 48 / 2 / 5000 |
| 本机端口 | 127.0.0.1:8001 → 容器 8000 |

evals/memory_candidate_v6.json 的 BM25/上下文参数是实验配置，不作为线上参数。此前诊断脚本的 contextual_retrieval 不是实际字段名，实际字段名为 contextual；该次 null 输出不用于判断线上开关。

## 接口地址与鉴权

| 用途 | 地址 / 方式 |
|---|---|
| Add | POST http://aixuexi.asia/v1/memories/add |
| Search | POST http://aixuexi.asia/v1/memories/search |
| 版本报告 | GET http://aixuexi.asia/v1/memories/version，需鉴权 |
| Health | GET http://aixuexi.asia/health |
| Readiness | GET http://aixuexi.asia/ready/memory |
| OpenAPI | GET http://aixuexi.asia/openapi.json |
| 鉴权 | Authorization: Bearer <Memory System Key>；有效值对应 MEMORY_API_KEY，只填平台专用字段 |

2026-10-10，我的公网检查记录为：health 200/ok、readiness 200/ready、OpenAPI 包含 Add/Search，错误令牌的 Add/Search 均返回 401。这次检查使用客户端默认网络路径，只发送无效令牌，没有发送有效密钥或写入评测数据。该记录不代替有效令牌真实 Add/Search 闭环。我按实际检查的 HTTP 地址列出 URL，这次没有记录 HTTPS 闭环。

Add 使用 request_id、user_id、session_id、messages，保留 role、content 和可选毫秒 timestamp；事务成功后返回 success=true 和对应标识，相同请求相同载荷幂等，不同载荷冲突。Search 使用 query、user_id、top_k、可选 options，按用户隔离，输出 data 证据数组，含 id/content/score/sources。options 不用于拼造答案；最终 Answer/Judge 在外部评测方执行。

## 容量与运行限制

| 项目 | 规格或实际口径 |
|---|---|
| 服务器 | 阿里云轻量，新加坡，Ubuntu 24.04，2 vCPU、4 GiB RAM、50 GiB 系统盘，峰值公网带宽 200 Mbps；依据 2026-10-10 控制台截图 |
| 存储 | PostgreSQL/pgvector，容器 tracememory-db-1，Compose 持久卷 memory_pgdata |
| 已有运行记录 | 平台 Smoke 截图：Add/Search 并发上限 16/16、Top K 100、46/46 完成；并发值是配置上限 |
| 请求体默认保护 | Add/Search 8 MiB，超过返回 413 |
| 单次 Add 默认保护 | 最多 20,000 块，与请求体预算分别检查 |
| Search 参数 | top_k 1～1000，截图使用 100；标识最多 512 UTF-8 字节 |
| Embedding 默认预算 | 每批最多 10 段；单次 HTTP timeout 30 秒；网络错误、超时、429、5xx 最多尝试 3 次，退避 0.5/1 秒 |
| 上游失败 | 返回明确错误，不伪造向量；多批请求累计耗时可超过单次 timeout |
| 上下文保护 | context_limit/link_hops/signal_scan_limit/evidence_bytes 仅在相应检索开关启用时适用 |
| 运维 | restart=unless-stopped，API stop_grace_period=60s；health 检查存活；readiness 的 Embedding 探测默认 900 秒过期 |

8 MiB/20,000/30 秒等为代码默认保护值，可由部署环境覆盖，不作为实测吞吐或并发保证。精确向量检索、父消息扫描、上游请求随数据规模影响耗时。系统保留原文，不自动裁定事实冲突或生成最终答案。

## 原始工作与模型披露

我参考的工作、原作者、仓库固定版本、论文、技术资料和具体改动见 [原始工作披露](original-work-v6.md)，AI 辅助情况见 NOTICE.md，依赖许可见 third-party-dependencies.md。

实际 Add/Search 使用 text-embedding-v4/1024；服务没有 gpt-4o-mini 事实抽取组件。我按实际实现披露模型使用情况，并遵循所选组别的对应规则。这次源码发布没有额外执行模型调用。本 commit 不自动继承历史版本得分。
