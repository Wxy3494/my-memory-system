# v6 发布验证（2026-10-10）

公开基线：142f0ddcdd2ccc06b044c47f2777a99d3b3707e9。原 v6 包 SHA256：93d5bcd2a8e3c36372adfe04cf8522f8f3858e2766db576fa7f577ce1576fb1d。我的发布校验记录确认 v6 文件夹与归档包逐文件一致，app/migrations 原样保留。

我整理了 README 和当前提交说明，补充来源披露，并校正依赖许可的旧状态；删除 v5/v6 配置的 official_smoke_evidence 历史字段，将发布辅助工具历史 run 常量改为 None。不导出 docs/evidence 等历史输出和含私有编号的历史文档。源码清单记录原包与实际文件 SHA256 及改动范围；原 v6 与备份不变。

我的离线验证命令：python -m unittest discover -s tests -p 'test_memory*.py'。93 项：76 通过，17 跳过真实数据库/模型探测，0 失败。Windows Python 3.13.12，FastAPI 0.141.1、Pydantic 2.13.5、psycopg 3.3.6、httpx 0.28.1、NumPy 2.5.3，监控依赖为本地 prometheus_client。Linux 锁文件 NumPy 为 2.3.5，本次不是 Linux 锁定环境测试；离线测试不代表部署数据库或模型验收。

公开检查工具离线单元测试：3 项通过，0 失败。我的这次离线验证共 79 项通过、17 项跳过。`git diff --cached --check` 通过；153 个暂存文件与公开哈希清单一致，26 个 app/migrations 文件与原包及指定 v6 完全一致；Python 源码语法检查通过，常见密钥/私有评测标识扫描未发现匹配。

我的公网无凭据检查记录：health 200/ok、readiness 200/ready、OpenAPI Add/Search 存在、错误令牌拒绝通过。使用 scripts/review_public_memory.py，只发送无效令牌，没有写入评测数据或调用模型。原始本机报告保存在公开工作区之外。

这次文档和源码发布保留了原有线上镜像、配置、数据库和平台绑定。我没有在发布过程中执行官方 Smoke/Full，历史得分仍对应原来的评测记录。部署实际口径见 competition-submission.md，来源见 original-work-v6.md。
