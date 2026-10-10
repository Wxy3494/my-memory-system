# 我的记忆系统：CSIG 文本记忆项目（v6）

这是我的 CSIG 文本记忆项目，内部名称是 TraceMemory，使用 MIT 许可，署名 Wxy3494。我在原客服 RAG 项目上扩展了文本记忆服务，两个阶段都使用了 AI 辅助。具体来源见 [原始工作披露](docs/original-work-v6.md)。

我在这里发布 v6 源码，对应的归档包是 my-memory-system-v6-local-review.zip，包 SHA256：`93d5bcd2a8e3c36372adfe04cf8522f8f3858e2766db576fa7f577ce1576fb1d`。app 与 migrations 保持包内容，逐文件对照见 [源码清单](source-manifest-v6.json)。我保留了此前的 Git 历史。引用固定版本时，请使用本次提交的完整 SHA。

我的服务将消息原文与来源存入 PostgreSQL/pgvector，在同一用户范围检索证据。Add 同步持久化，Search 返回原文证据，不生成最终答案。v6 包含 BM25、邻近消息、父消息上下文、来源关联与保守时间线索等可选机制；我的线上部署记录中的配置为 vector / pipeline_version=v0。v6 是源码发布名称，v0 是存储与分块签名参数，平台自定义版本标签也不是源码版本号。

- [提交说明：部署版本、接口、鉴权、容量和运行限制](docs/competition-submission.md)
- [原始工作：作者、固定仓库、论文与改动](docs/original-work-v6.md)
- [本次发布验证](docs/v6-release-verification.md)
- [第三方依赖许可](docs/third-party-dependencies.md)

## 运行与验证

我的记忆服务使用的依赖为 requirements-memory.txt 与 requirements-memory.lock.txt。配置模板为 .env.memory.example，实际配置与有效密钥仅保存在部署环境。容器入口 app.memory_main:app；迁移入口 scripts/memory_admin.py migrate；部署定义 compose.memory.yaml。离线 Dockerfile 另需自行准备 wheel，仓库不含第三方 wheel 二进制。

```sh
python -m unittest discover -s tests -p 'test_memory*.py'
python -m unittest discover -s tests -p 'test_public_memory_review.py'
```

数据库集成测试须显式配置独立的 *_memory_test 数据库，模型探测须显式启用。evals/memory_*.jsonl 为自建合成资料，每条包含 provenance，不属于官方题库或官方金标。Answer/Judge 自测脚本位于 evals，服务 Add/Search 不调用它们。

docs 内其他带日期文档为历史记录，其配置、结果与发布状态以当时日期为准；当前发布以上述 v6 文档为入口。我保留了原客服模块供溯源，参赛记忆 API 使用独立运行入口。
