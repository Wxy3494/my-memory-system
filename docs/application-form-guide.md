# 学生研究原型的申请表填写准备

日期：2026-10-06。用户说明自己是学生，个人参赛，系统名“我的记忆系统”。先按学术研究原型准备材料；这不代表已经提交或获批。用户已改为授权公开 GitHub 仓库并选择 MIT 许可证；链接与固定 Commit 需在上传验证后填写。

## 已查明的模型规则

官方赛事 FAQ 区分两类组件：学术榜 Embedding 使用 text-embedding-v4，LLM 相关组件使用 gpt-4o-mini，Reranker 不限。当前实现的 Embedding 已使用 text-embedding-v4，不需要把向量模型名称改成 gpt-4o-mini。当前系统没有 LLM 抽取或生成组件。

申请表和 Full 检查项的模型说明比 FAQ 更宽泛，尚未从公开说明中确认“没有 LLM 的 Add 是否必须增加一次 gpt-4o-mini 调用”。现有方案是常见的原文分块、向量编码、用户范围检索，不冒充已经取得学术榜资格认可。不为消除文案疑义就擅自加入付费生成调用、改变 pipeline 或改写原文。

工业榜允许非商业项目参加，且无需公开内部实现；学生身份并不强制选择工业榜。工业/商业组别不参与本期奖金评选。当前按学生研究原型准备学术材料；如果继续保持源码不公开，该表要求的公开仓库条件仍未完成，不能编造链接。

来源：[赛事 FAQ 第 05 项](https://agentmemoryleaderboard.ai/competition/)、[参赛说明](https://agentmemoryleaderboard.ai/rules)、[官网申请表代码](https://agentmemoryleaderboard.ai/static/app.js?v=blog-production-20261001-email-preflight-20261003)。读取摘要和哈希见 `evidence/20261006-memory-local-closeout/official-rule-check.json`。

## 填写对应关系

| 表单项 | 内容 |
|---|---|
| 榜单 | 学术榜，研究原型准备路径；审核决定资格 |
| 邮箱、姓名 | 用户在页面填本人的真实信息 |
| 组织/团队 | 没有团队可填“个人（学生）”；不要编造学校或机构 |
| 邀请码 | 没有就留空 |
| 系统名 | 我的记忆系统 |
| 版本 | 最终上线后固定版本名称与 commit/镜像；当前本地候选 v0-vector-local |
| Add/Search | 真实部署域名下的 /v1/memories/add 与 /v1/memories/search；当前没有公网地址 |
| 鉴权 | Authorization: Bearer，和当前代码一致 |
| Memory System Key | 仅在平台安全字段填写上线时轮换后的 MEMORY_API_KEY；不填模型 Key 或 Eval Key |
| 高级接口 | 同步实现不需要 Add-status；如果填写 Health，使用真实域名的 /health |
| 公开仓库 | 确认许可并公开后填真实 URL；用户许可暂缓，当前留空且不提交 |
| 提交说明 | 描述方法、AI 辅助、实际版本、域名、容量、超时与来源限制；不要声称已经上线或取得官方分数 |

## 尚未提交的说明草稿

“我的记忆系统”是个人学生开发的文本对话记忆研究原型，使用 AI 辅助构建。采用 FastAPI、PostgreSQL/pgvector、text-embedding-v4（1024 维）。Add 同步保存原文及来源并完成向量入库；Search 仅在同一 user_id 范围内返回排序的原文证据，不生成最终回答。实现鉴权、重试幂等、冲突检测和事务提交。当前没有 LLM 事实抽取、摘要或重排。

已完成本机真实模型闭环、100 题合成诊断、同用户 1000 条短消息串行样本和合成库备份恢复一致性检查。诊断候选只有 25～49 个块，Recall@100 不具有强方法区分力；没有官方 Answer/Full 分数。当前未部署公网，许可和公开仓库待确认。线上 URL、最终 commit/镜像、实测并发/容量与费用配额应在部署后替换为真实信息。

这是准备稿，包含未完成状态，不能直接当成完整申请提交。服务器和公网按用户此前决定后置；真实评测需稳定在线服务，平台不会代部署。
