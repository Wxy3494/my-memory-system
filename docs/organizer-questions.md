# 申请前待向主办方核实的问题（草稿，未发送）

公开资料核对补充：2026-10-06 已直接读取官方赛事 FAQ，Embedding 要求为 text-embedding-v4，LLM 组件为 gpt-4o-mini；工业榜无商业化前提。申请表仍有更宽泛的模型说明。因此第 1 项仅剩“无 LLM 的 Add 是否要求增加 LLM 调用”的适用性问题，不再把当前向量模型本身误认为不符合指定模型。学生原型的填表对应关系见 `application-form-guide.md`。本文件没有发送给主办方。

个人参赛，系统名称“我的记忆系统”，文本记忆赛道。当前本地实现是 AI 辅助开发的 FastAPI/PostgreSQL 记忆服务。Add 原样保存对话并使用 text-embedding-v4 编码；Search 返回原文来源证据。没有生成模型做事实抽取或摘要，没有使用平台题目、金标或私有评测数据。

需要核实：

1. API 指南的开源方法 Full 检查项提及 Add 使用 gpt-4o-mini，而架构说明允许自选内部实现。仅执行原文存储与 Embedding、不使用生成模型的 Add 是否可参加开源方法榜？是否有特殊申请或披露要求？
2. 当前个人已选择 MIT 并准备公开固定版本；请确认该学生原型适用的组别，特别是没有生成模型组件的 Add 应如何申请，不预先声称已获资格认可。
3. AI 辅助构建代码的来源、人工署名和方法改动披露是否有指定格式或补充要求？

出处（2026-10-06读取）：[参赛说明](https://agentmemoryleaderboard.ai/rules)、[API 指南](https://agentmemoryleaderboard.ai/api-guide)。本文件不代表主办方答复，不含密钥。
