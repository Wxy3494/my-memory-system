# TraceMemory 设计与接口

实现日期：2026-10-06。以项目内 `docs/evidence/20261006-memory/` 的当前验证记录为准。

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

载荷按 JSON 键序计算哈希，消息数组顺序、时间、角色、会话和正文均参与。缺省 timestamp 与显式 null 视为同一有效载荷。相同 `(user_id, request_id)` 和载荷回显成功，变化返回 409。向量请求位于事务外；最终事务使用请求范围 advisory lock，再查幂等记录，并一次提交全部数据。并发重试可能重复计费，数据库只形成一份逻辑写入。并发计数和事务中途失败的完整回滚已在真实 PostgreSQL/pgvector 测试库验证；模型调用仍使用假向量。

模型、地域 base URL、维度、pipeline、分块预算、Embedding 输入格式均参与持久化签名；改变这些配置后拒绝继续混用索引。升级应新建独立数据库并重建，不能改签名冒充完成迁移。

## 分块与来源

当前分块器以 UTF-8 字节作为保守预算，尽量在末段句末/换行处分割。配置沿用方案中的 TOKEN 名称，**它不是精确 Qwen tokenizer 的 token 计数**。默认目标 400 字节、重叠最多 60 字节，比 400 个实际 tokens 更保守。所有字符完整覆盖，来源偏移是 Python Unicode 字符位置，包含重叠；长文末尾不会被丢掉。

Embedding 输入为说话人、源 timestamp 前缀和片段原文；数据库片段仍存完整原文切片。白字符片段有来源前缀，避免只发送空白给模型。一次请求最多 10 条，显式 dimensions=1024，按返回 index 重排，检查条数、重复 index、维度、有限数值和零向量。仅对网络超时、429、5xx 有界重试，不切换模型。[百炼官方向量接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api/)

Search 的长问题全量分段向量化，按 UTF-8 长度加权平均后归一化；不会截到前 2000 字。options 被接收，但不充当答案或写进证据。返回 content 的来源前缀保留 role/source timestamp/session/ordinal/offset，正文是原文切片；sources 提供消息 ID、请求和偏移用于审计。没有推断事件时间，没有把 assistant 建议改成用户事实。

## 检索与可选改进

默认 vector：SQL 内 MATERIALIZED 用户范围，再精确 cosine 距离排序，平分时用 chunk ID 稳定排序。同用户可跨会话搜索，不在全库 top-k 后做应用过滤。

hybrid 为实验开关：在同一用户范围增加英文词项、编号及中文二元字符检索；按命中词项数排名，再以 RRF(k=60) 合并。每路最多 max(200, 2×top_k) 候选，中文路径并非英文 BM25。词项路径最多 128 个唯一词项，向量路径仍表示完整 query。此开关未证明收益，正式版本默认不启用。相邻窗口、事实层、图数据库和自动“最新覆盖旧值”未实现。

## 安全、就绪和运营

每请求仅记录服务器随机编号、固定路由、状态和耗时。记忆请求不进入 LangSmith 追踪，指标不含用户标签、正文或令牌。paid tokens 来自上游 usage，不估造缺失值。

就绪接口不主动调用付费模型，使用当前进程实际请求成功/失败缓存，默认有效期 900 秒。启动后未发生请求时会 503；先用自建样例跑 Add/Search 后可就绪。CLI probe 的缓存不与 API 进程共享，不能将 CLI 成功当成 API 已就绪。多 worker 各自有缓存，当前部署单 worker。

清理命令按确切用户 ID 删除，外键级联删除原文、片段及来源。数据卷、备份、日志和本地评测输出仍需按部署记录清理；平台数据不得放入展示报告。
