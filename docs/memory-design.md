# TraceMemory 设计与接口

当前v6：message_signals的解析版本v2按事实/事件来源范围关联日期；不确定关联、相对时间、计划与撤回恢复的状态不强行消解。当前态按相关主体选日期，全局按事件主题/时期分桶；重复片段去重并有界保留首尾，最多96事件/32事实。内部schema3，显式迁移回填旧版本/损坏索引，原文和向量保留。仍最多扫描5000条索引、24父消息、2轮补证，保护原前5，仅输出原文来源。见 [v6报告](remediation-v6-review-fixes-20261008.md)。以下为历史。

三轮v4覆盖规则：先定位父消息，按查询词项、局部词项差异及头中尾返回最多8个候选；逐父消息扫描文本块，不读取Embedding。每种子最多8个扩展块，每消息每种子最多6个；种子和总字节预算保护保留。同分优先来源字段，跨消息字符偏移不用于相关性判断。扫描成本线性，任意内部隐含事实仍可能漏检。最新记录见 [三轮报告](remediation-round3-20261007.md)，以下二轮参数为历史规则。

二轮检索补充：邻近窗口先预留能够容纳的种子条数及完整证据字节，再交错扩展；每种子最多增加4块，每消息每种子最多2块，SQL每目标消息最多取4块。字节预算包括来源头，不截断原文；预算不足可能无法返回所有种子。窗口路线的 score 为最终排名倒数，不是余弦相似度；余弦门槛在扩展前判断。纯 BM25 且未启用余弦门槛时不编码查询、不运行向量查询；Add 仍需 Embedding，BM25仍扫描该用户全量块。`003_memory_neighbor_index.sql` 提供按消息/偏移查找的索引。最新验证边界见 [二轮报告](remediation-round2-20261007.md)。

更新日期：2026-10-07。旧基线真实运行记录在 `docs/evidence/20261006-memory/`；新候选和验证范围见 `remediation-20261007.md`，不混用两者。

## 定位与边界

文本记忆赛道：原文消息入库、同步向量化、按用户召回、保留说话人和来源。不生成最终答案。客服场景由原 `/ask` 和 `/v1/retrieve` 保留，赛事检索不进入这些分流。

本次实现路径是比赛目录中已放入的 `ai-customer-service-rag`，不回写另一个旧目录。

默认模型 `text-embedding-v4`，1024 维；不使用 LLM。官网问答对学术榜模型的要求与组别命名仍需申请时核实，不能据此保证奖金资格。[官方赛事问答](https://agentmemoryleaderboard.ai/competition/)

## 外部契约

所有 Add/Search 使用 `Authorization: Bearer <MEMORY_API_KEY>`。`GET /health` 和 `GET /ready/memory` 可无认证调用；前者只表示进程存活。[官方接口指南](https://agentmemoryleaderboard.ai/api-guide)

| 接口 | 请求 | 返回 |
|---|---|---|
| POST `/v1/memories/add` | request_id、user_id、session_id、messages | success=true，原样回显三个 ID |
| POST `/v1/memories/search` | user_id、query、top_k；可选顶层 options | 有序 data，每项 id/content/score，以及扩展审计 sources |
| GET `/ready/memory` | 无正文 | 配置、数据库迁移、最近上游状态；未探测/过期为 503 |

messages 仅支持 user/assistant 和非空文本；timestamp 为可选非负 Unix 毫秒。保留正文和标识字符串原值、消息顺序，不做大小写转换或裁剪。NUL/非法 Unicode 不能存入 PostgreSQL，返回 422。标识最多 512 UTF-8 字节，避免数据库复合索引超限。top_k 必填、整数 1～1000，正式测试支持 100；空检索返回 `data: []`。请求默认上限 8 MiB，Add 最多 20000 片段，超限明确 413。这些是实现能力边界，尚未证明上限负载可承载。

```json
{
  "request_id": "local-write-001",
  "user_id": "local-user-a",
  "session_id": "local-session-01",
  "messages": [{"role": "user", "content": "我习惯周五下午开项目会。", "timestamp": 1704067200000}]
}
```

```json
{"user_id":"local-user-a","query":"我的项目会通常安排在什么时候？","top_k":100}
```

## 持久化与重试

`migrations/001_memory.sql` 创建独立 `memory` schema，FAQ 表不参与迁移。四张业务表为 ingest_requests、messages、chunks、chunk_sources，额外 schema_version 记录迁移和 pipeline 签名。复合外键约束用户一致，按用户建立索引。

`002_memory_order.sql` 是追加迁移，schema 升至 2。新写入先取得请求锁，再取得同用户同会话锁，以当前最大值分配连续 `received_ordinal`，幂等重试不分配新序号。跨会话仍不假定存在全局源顺序。历史数据按 stored_at/request/ordinal 确定性回填，明确标为 `legacy_ingest_reconstructed`，不冒充原始先后。代码当前要求 schema=2，部署前须在隔离 PostgreSQL 演练迁移；本轮仅通过 SQL 解析及离线来源契约检查。

载荷按 JSON 键序计算哈希，消息数组顺序、时间、角色、会话和正文均参与。缺省 timestamp 与显式 null 视为同一有效载荷。相同 `(user_id, request_id)` 和载荷回显成功，变化返回 409。向量请求位于事务外；最终事务使用请求范围 advisory lock，再查幂等记录，并一次提交全部数据。并发重试可能重复计费，数据库只形成一份逻辑写入。并发计数和事务中途失败的完整回滚已在真实 PostgreSQL/pgvector 测试库验证；模型调用仍使用假向量。

模型、地域 base URL、维度、pipeline、分块预算、Embedding 输入格式均参与持久化签名；改变这些配置后拒绝继续混用索引。升级应新建独立数据库并重建，不能改签名冒充完成迁移。

## 分块与来源

分块器以 UTF-8 字节为预算，默认 400 字节、重叠最多 60 字节。新配置名为 `MEMORY_CHUNK_TARGET_BYTES` / `MEMORY_CHUNK_OVERLAP_BYTES`；缺省时兼容旧 `*_TOKENS` 名称。它不是提供商 tokenizer 的 token 计数。等值改名不改变签名或现有向量；改变预算仍须重建对应索引。Unicode 原文完整覆盖，偏移按 Python 字符位置记录。

Embedding 输入为说话人、源 timestamp 前缀和片段原文；数据库片段仍存完整原文切片。白字符片段有来源前缀，避免只发送空白给模型。一次请求最多 10 条，显式 dimensions=1024，按返回 index 重排，检查条数、重复 index、维度、有限数值和零向量。仅对网络超时、429、5xx 有界重试，不切换模型。[百炼官方向量接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api/)

Search 的长问题全量分段向量化，按 UTF-8 长度加权平均后归一化；不会截到前 2000 字。options 被接收，但不充当答案或写进证据。返回 content 的来源前缀保留 role/source timestamp/session/ordinal/offset，正文是原文切片；sources 提供消息 ID、请求和偏移用于审计。没有推断事件时间，没有把 assistant 建议改成用户事实。

新 content 前缀还包含 request_id、received_ordinal、stored_at、order_basis 和时间语义说明。消息时间来自 timestamp，入库时间来自数据库，事件时间保留在原文；不把候选排名当作时间排序。来源审计兼容旧记录，同时拒绝新顺序字段与原文/前缀不一致的证据。

## 检索与可选改进

默认 vector：SQL 内 MATERIALIZED 用户范围，再精确 cosine 距离排序，平分时用 chunk ID 稳定排序。同用户可跨会话搜索，不在全库 top-k 后做应用过滤。

hybrid 保留原词项命中数/RRF(k=60) 路径；新增 bm25 和 hybrid_bm25。BM25 使用拉丁编号/CJK 二元字符的词频、逆文档频率及长度归一化（k1=1.2,b=0.75）；按用户扫描并在进程内排序，成本随该用户块数增长。128 个词项上限仅作用于 query，原文词频不截断。

`MEMORY_NEIGHBOR_WINDOW` 默认 0，开启后从最多 `MEMORY_SEED_LIMIT` 个种子扩展同用户同会话相邻接收序号及同消息片段，按 ID 去重。种子优先，邻近片段按接收序号与偏移排列，关联片段继承种子排名分而非声称自身 cosine 相似度。`MEMORY_EVIDENCE_BYTES` 默认 0（不额外限量），开启后按整条带来源前缀的证据选择，绝不截断原文。

`MEMORY_MIN_SIMILARITY` 默认空，只在开发集校准后启用；对问题的最高真实 cosine 做门槛，不对 RRF/BM25 比较，也不逐跳过滤低相似支持。无可用门槛时继续禁用。事实层和通用语义忘记/撤回删除尚未实现；对话限制的最终遵守需要真实 Answer/Judge 验证，管理员 purge 仍不等同语义治理。

## 安全、就绪和运营

每请求仅记录服务器随机编号、固定路由、状态和耗时。记忆请求不进入 LangSmith 追踪，指标不含用户标签、正文或令牌。paid tokens 来自上游 usage，不估造缺失值。

就绪接口不主动调用付费模型，使用当前进程实际请求成功/失败缓存，默认有效期 900 秒。启动后未发生请求时会 503；先用自建样例跑 Add/Search 后可就绪。CLI probe 的缓存不与 API 进程共享，不能将 CLI 成功当成 API 已就绪。多 worker 各自有缓存，当前部署单 worker。

清理命令按确切用户 ID 删除，外键级联删除原文、片段及来源。数据卷、备份、日志和本地评测输出仍需按部署记录清理；平台数据不得放入展示报告。
