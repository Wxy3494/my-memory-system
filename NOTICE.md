# 来源与许可

我以 Wxy3494 署名发布“我的记忆系统”，内部工程名称是 TraceMemory，以个人身份参赛。项目采用 MIT 许可，见 LICENSE。

我在原客服 RAG 项目上扩展了文本记忆服务。原项目和后续改造都使用了 AI 辅助，记忆模块的开发包含 Codex 辅助。下文列出已记录的来源；对潜在第三方复用的排查仍有范围限制。

2026-10-07 的方法核验涉及 LlamaIndex（Jerry Liu，MIT）的句子窗口，以及 LangChain（LangChain, Inc.，MIT）的父子文档和多向量检索。我参考了这些设计思路，在现有消息与分块结构中实现原文上下文扩展，没有引入这两套框架或复制其函数。固定版本、原作者、公开源码与许可链接、方法取舍见 `docs/original-work-v6.md` 和历史 `docs/github-methods-20261007.md`。本地证据树保留上游快照与许可用于审计，本次公开整理没有上传这些快照。示例默认模型没有用于本项目，Embedding 配置仍按实际实现披露。

版权署名为 Wxy3494。依赖软件分别适用各自的原始许可，本项目的 MIT 许可不替代第三方依赖许可，也不授予额外权利。

依赖记录见 `docs/third-party-dependencies.md`；方法与改动见 `docs/competition-submission.md`、`docs/memory-change-summary.md`。当前部署与提交说明见 docs/competition-submission.md；所选参赛组别的最终准入仍需确认。
