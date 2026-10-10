# 学生研究原型的申请表填写准备

更新：2026-10-07。个人学生参赛，系统名“我的记忆系统”；尚未申请或获批。公开仓库 https://github.com/Wxy3494/my-memory-system，MIT；历史已核验 commit 为 142f0ddcdd2ccc06b044c47f2777a99d3b3707e9。新整改候选尚未公开或部署，最终申报须重新冻结。

## 已查明的模型规则

官方赛事 FAQ 区分两类组件：学术榜 Embedding 使用 text-embedding-v4，LLM 相关组件使用 gpt-4o-mini，Reranker 不限。当前实现的 Embedding 已使用 text-embedding-v4，不需要把向量模型名称改成 gpt-4o-mini。当前系统没有 LLM 抽取或生成组件。

申请表和 Full 检查项的模型说明比 FAQ 更宽泛，尚未从公开说明中确认“没有 LLM 的 Add 是否必须增加一次 gpt-4o-mini 调用”。现有方案是常见的原文分块、向量编码、用户范围检索，不冒充已经取得学术榜资格认可。当前实现保留原有 pipeline 与原文处理方式，没有增加付费生成调用。

当前按学生研究原型准备开源方法材料。历史基线仓库已公开，新候选仍需发布并核对线上版本；个人或学生身份本身不能代替组别审核。

来源：[赛事 FAQ 第 05 项](https://agentmemoryleaderboard.ai/competition/)、[参赛说明](https://agentmemoryleaderboard.ai/rules)、[官网申请表代码](https://agentmemoryleaderboard.ai/static/app.js?v=blog-production-20261001-email-preflight-20261003)。读取摘要和哈希见 `evidence/20261006-memory-local-closeout/official-rule-check.json`。

## 填写对应关系

| 表单项 | 内容 |
|---|---|
| 榜单 | 学术榜，研究原型准备路径；审核决定资格 |
| 邮箱、姓名 | 我的真实姓名与邮箱，仅填写在申请页面 |
| 组织/团队 | 没有团队可填“个人（学生）”；不要编造学校或机构 |
| 邀请码 | 没有就留空 |
| 系统名 | 我的记忆系统 |
| 版本 | 最终上线后固定版本名称与 commit/镜像；当前本地整改候选 v2-local-review，尚未申报 |
| Add/Search | 当前 HTTP 地址为 http://aixuexi.asia/v1/memories/add 和 http://aixuexi.asia/v1/memories/search；真实外网闭环与最终版本冻结待验收 |
| 鉴权 | Authorization: Bearer，和当前代码一致 |
| Memory System Key | 仅在平台安全字段填写上线时轮换后的 MEMORY_API_KEY；不填模型 Key 或 Eval Key |
| 高级接口 | 同步实现不需要 Add-status；如果填写 Health，使用真实域名的 /health |
| 公开仓库 | https://github.com/Wxy3494/my-memory-system；MIT，Wxy3494；上述 commit 仅为历史基线，新候选待发布 |
| 提交说明 | 描述方法、AI 辅助、实际版本、域名、容量、超时与来源限制；不要声称已经上线或取得官方分数 |

## 尚未提交的说明草稿

我以个人学生身份开发“我的记忆系统”，这是一个使用 AI 辅助构建的文本对话记忆研究原型。采用 FastAPI、PostgreSQL/pgvector、text-embedding-v4（1024 维）。Add 同步保存原文及来源并完成向量入库；Search 仅在同一 user_id 范围内返回排序的原文证据，不生成最终回答。实现鉴权、重试幂等、冲突检测和事务提交。当前没有 LLM 事实抽取、摘要或重排。

旧基线有本机真实模型闭环、100 题诊断和 1000 条串行样本记录。新候选新增 100 道有效答案题和 32 个七项能力情境，以及独立严格 Answer/Judge 工具；目前仅离线词项与契约验证，没有新候选的模型答案或官方分数。旧基线公开仓库已核验，新候选公开 commit、最终镜像、真实外网闭环、云端容量及配额仍待验证。

这是准备稿，包含未完成状态，不能直接当成完整申请提交。真实评测需稳定在线服务，平台不会代部署。
