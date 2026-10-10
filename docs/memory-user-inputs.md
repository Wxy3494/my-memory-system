# 我的运行配置与外部依赖

代码、迁移、测试、合成数据、部署文件和检查入口已在本项目中准备。以下列出运行所需的外部配置。我的真实密钥只保存在本地或服务器配置中，不写入公开文档。

当前进度补充：模型 Key/base URL、数据库密码和服务令牌已在我的本机配置，真实闭环、100 题诊断和 1000 条串行样本已完成；这些凭据的截图暴露后轮换尚未执行。我以个人身份参赛，项目名称是“我的记忆系统”，公开仓库采用 MIT 许可。云端进展见 publication-status.md。下表说明用途，不能将已配置项目误读为仍需从零配置。历史未完成项记录在 `local-release-status.md`；当前部署信息见 competition-submission.md。

| 补充项 | 用途 / 配置位置 | 现在是否必须 |
|---|---|---|
| 百炼 text-embedding-v4 可用账号及 API Key | `.env.memory` 的 MEMORY_EMBEDDING_API_KEY | 真实记忆闭环必须 |
| 对应地域/业务空间 HTTPS 兼容 base URL | MEMORY_EMBEDDING_BASE_URL；代码追加 /embeddings | 必须，与 Key 地域一致 |
| 模型 RPM/TPM 配额及费用上限 | 小样、容量、Full 预算；先实测再申报并发 | Full 前必须 |
| 自定义随机 Memory System Key | MEMORY_API_KEY；平台用于 Bearer 调用 | 必须，和模型 Key 分开 |
| 可用的 Linux 云服务器/现有主机 | 公网、Docker Engine/Compose、磁盘持久化及出站 HTTPS | 公网评测必须 |
| 域名及 DNS 管理能力 | MEMORY_PUBLIC_HOST，服务器开放 80/443，Caddy 自动 HTTPS | 使用本方案 HTTPS 部署必须 |
| 数据库密码 | POSTGRES_PASSWORD；宿主机开发另填 DATABASE_URL | 必须；Compose 自带 pgvector |
| 服务器登录配置 | 我的本机 SSH 配置；公开资料仅记录主机与用户名等非秘密信息 | 服务器登录需要 |
| 团队/联系人/项目公开名称 | 参赛申请和 competition-submission.md | 申请时必须 |
| 公开 GitHub 仓库、开源许可、来源归属 | 开源方法榜开放材料与固定 Commit | 选择开源方法榜必须 |
| 榜单归属及无 LLM 的 V0 是否满足要求 | 申请时核对当前主办方解释 | Full 前核实 |
| 官方签发的 Eval Key | 官方页面 Smoke/Full；不要填进本服务 | 申请审核后取得 |

当前赛事模块不需要 DeepSeek、gpt-4o-mini、GPU、本地 BGE 缓存或真实订单接口。若保留旧客服演示，则其依赖仍按原 README 配置。V2 事实抽取没有实现，也不作为本次 V0 外部配置前提。

Full 数据规模、模型配额和同用户精确检索都会影响要求，不能用目前离线测试直接承诺容量。

真实值放 `.env.memory`，模板是 `.env.memory.example`；不要直接覆盖复制项目里的旧 `.env`。配置完后按 `memory-deployment.md` 运行，留下真实证据再更新提交状态。
