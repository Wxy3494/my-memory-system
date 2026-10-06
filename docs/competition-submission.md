# 参赛提交说明模板（未提交）

日期：2026-10-06。系统展示名称：我的记忆系统。内部工程名称：TraceMemory。赛道：Textual。候选版本：v0-vector-local；未申报正式版本。

## 方法说明

以原 ai-customer-service-rag FastAPI 项目扩展文本对话记忆服务。将 source messages 原样保存在 PostgreSQL 独立 schema，以 Unicode 原文偏移分块；使用 text-embedding-v4 / 1024 维编码，SQL 在 user_id 内精确向量检索。Search 输出排序的原文证据和来源，不生成最终回答。role、源毫秒时间、session 及顺序均保留。同请求原载荷幂等、不同载荷冲突；写入事务完成后才返回 success。

默认不启用实验 hybrid；若最终选择 hybrid，必须重写本节、更新版本及附上消融结果。没有 LLM 事实抽取/摘要、图数据库或多 Agent。向量模型由外部服务提供，数据库、带宽和 API 由参赛方自托管。

## 尚待填写

| 字段 | 内容 |
|---|---|
| 团队 / 联系人 / 联系方式 | 用户确认是学生、个人参赛；展示系统名为“我的记忆系统”。联系人署名和联系方式由用户在申请页面填写 |
| 参赛组别与资格核实记录 | 按学生研究原型准备学术榜材料，尚未申请或获批。官方 FAQ 指定学术 Embedding 为 text-embedding-v4、LLM 组件为 gpt-4o-mini；当前无 LLM，Add 是否须额外调用 LLM 的措辞仍未完全一致。详见 application-form-guide.md |
| 公开仓库 URL / 许可 / 作者 | 用户已授权公开仓库；MIT 许可证，署名 Wxy3494；仓库 URL 在上传验证后填写。AI 辅助来源已披露，依赖清单见 third-party-dependencies.md |
| 固定 Commit / 源码哈希清单 | 本地交付版本通过 Git 提交保存；实际 commit 与包哈希见 releases/release-info.json。正式申报前重新冻结线上代码与镜像 |
| API 镜像、Python / DB / 网关 image digest | 本地 API 镜像已构建，见 docker.json；正式版本冻结与线上 digest 待核对 |
| Add URL | https://实际域名/v1/memories/add |
| Search URL | https://实际域名/v1/memories/search |
| Health URL | https://实际域名/health |
| 认证 | Bearer；Memory System Key 仅填写平台专用字段 |
| 模型地域、精确 model / dim / 分块配置 | text-embedding-v4 / 1024；实际冻结配置待附 |
| 实测 Add/Search 并发、超时、存储、配额 | 本机同用户 1000 条短消息、并发 1：10 批 Add、20 次 Search，无错误；Search P95 约 386ms。更大规模、并发、峰值与云端配额待验证 |
| 自建数据集哈希和检索/负载记录 | 真实 vector 开发 60 题与留出 40 题已完成；93 道有证据题 Recall@5/20/100=1.0，7 道无答案题单列，无泄露或审计错误。报告与哈希见 docs/evidence/20261006-memory-live/；模板诊断集结果不代表官方成绩 |
| 公网与平台 Smoke Run/Job ID | 未执行 |
| Full / 审核状态 | 未执行 / 未审核 |

开源方法榜的 MIT 许可已确定，公开仓库正在准备，不能将“暂不公开”自动当成已经选择商业产品榜。官网 API 指南在 Full 检查项写明开源方法 Add 的模型要求，而当前实现只使用 Embedding、不调用生成模型；这个方案的组别适用性须由主办方明确后再申报。核实问题草稿见 `organizer-questions.md`，没有代发邮件或消息。

## 复用与改动披露

复用用户提供的客服 RAG 项目，包括 FastAPI 服务组织、SQL 使用及脱敏监控。用户于 2026-10-06 确认原项目使用 AI 辅助构建；后续文本记忆服务改造也有 Codex AI 辅助，不宣称全部由用户独立编码。这一说明不等于已核实全部代码来源或取得第三方授权；如含参考或复用代码，应补充对应来源与许可。没有把原客服 FAQ 成绩当成记忆项目成绩。新增模块和逐文件改动见 `memory-change-summary.md`。

数据库/向量/HTTP 依赖分别来自 PostgreSQL、pgvector、psycopg、FastAPI/Pydantic、httpx、Prometheus 等项目，遵循各自许可。RRF 融合的实验实现采用固定 1/(60+rank) 排名累加，来源：Cormack, Clarke, Büttcher, 2009, “Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods”。正式启用时须附论文引用与本地对照结果。

本次新增实现有 Codex AI 辅助，不应在面试或材料中宣称全部由用户独立编码。提交者应审查代码、确认许可和原始工作署名，然后作出符合赛事规则的披露。

修复本地评测器首行和来源字段漏检，新增污染/角色/时间/会话篡改测试，并使用原始 100 题输出再次审计；不产生新模型请求。见 `evidence/20261006-memory-local-closeout/strict-replay.json`。每题完整候选仅 25～49 个块，忽略问题的全量基线 Recall@100 也为 1.0；小 K 对照才能反映这组数据上的排序作用。真实 vector 开发集 Recall@5=1.0，忽略问题的 ID 排序基线约 0.161；留出集分别为 1.0 和约 0.243。不能据此宣称官方成绩或复杂长期记忆能力达标。

无源时间的同会话跨多个 Add 目前仅保存请求内 ordinal，返回 content 没有持续写入顺序；时间先后判别存在限制。该项没有在本轮修改运行代码，后续若改进需新版本与对应验证。

## 未完成验收与声明

已有离线协议、失败路径、旧功能回归、真实 PostgreSQL/pgvector 事务集成、数据库容器重启、真实 Embedding 小样、真实 Add/Search 与 API 重启后再检索记录，见 `docs/evidence/20261006-memory-live/acceptance.md`。自建 100 题检索诊断和同用户 1000 条串行容量样本已完成；更大规模、并发、峰值内存、公网和平台 Smoke/Full 尚未完成。用户已决定先做本地评测与材料，将服务器/公网后置。只有材料完整、Smoke 通过、Full 完成、版本一致并通过复核后，才可称有效提交。[官方参赛说明](https://agentmemoryleaderboard.ai/rules)

平台数据只服务当前评测；不用于训练或公开展示，依要求清理主数据和副本。[官方数据与接口指南](https://agentmemoryleaderboard.ai/api-guide)
