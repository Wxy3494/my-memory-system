# 申请前版本核对

2026-10-06，使用匿名 git ls-remote 和独立浅克隆读取公开仓库。

- 仓库：https://github.com/Wxy3494/my-memory-system
- 固定 commit：142f0ddcdd2ccc06b044c47f2777a99d3b3707e9
- LICENSE：MIT，Copyright (c) 2026 Wxy3494。
- 公开版本的 13 个记忆 API 运行代码文件与本地候选逐文件 SHA-256 一致。记录：`evidence/20261006-public-repo-runtime-hashes.json`。
- 线上容器源码和非敏感配置仍需读取后比较；公开仓库与本地一致不能替代线上版本核验。

本次重新读取的[赛事 FAQ 第 05 项](https://agentmemoryleaderboard.ai/competition/)区分 Embedding（text-embedding-v4）和 LLM 组件（gpt-4o-mini）。本地记忆接口没有生成模型调用，Embedding 模型硬性校验为 text-embedding-v4、1024 维。据 FAQ，当前 Embedding 选型符合该项要求；没有 LLM 组件是否仍必须调用 gpt-4o-mini，FAQ 未明确要求，而申请表/Full 检查项措辞更宽泛。申请说明应如实披露无 LLM 的方法，最终资格由主办方审核。

[官方参赛说明](https://agentmemoryleaderboard.ai/api-guide)明确先提交固定版本和材料，审核后发放 Eval Key，再运行 Smoke/Full。官方 Smoke/Full 尚未完成不妨碍先申请。

此次未提交申请、未发送邮件、未改变线上服务或鉴权。

## 23:31 用户提供的线上输出

用户终端截图显示源码指纹为 `28fb15d80bc37953830501f3e0c522d2d82058709db9e6944f84d9a3455e0116`，与公开 commit 的上述 13 个文件聚合指纹完全一致。此证据覆盖记忆 API Python 代码，不覆盖全部依赖、数据库迁移或部署配置。

配置输出：model=text-embedding-v4，dimension=1024，pipeline_version=v0，retrieval=vector，chunk_target=400，chunk_overlap=60。申请版本可写 v1.0，但说明其内部 pipeline_version 为 v0，并绑定上述固定 commit。

截图同时暴露了记忆 API 密钥明文。本记录不保存该值；提交前需要更换该密钥并同步申请表。未执行更换。
