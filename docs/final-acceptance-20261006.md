# TraceMemory 最终验收记录（尚未通过发布验收）

检查日期：2026-10-06。用户授权直接验收、修复并整理项目。只改验收工具和说明，未修改 API、数据库迁移、模型或检索配置，未安装系统软件、操作生产数据库或重启生产服务。

## 本轮实测

### 后续云端截图验收（2026-10-06 23:06，北京时间）

用户在阿里云 Workbench 执行 `sudo docker exec tracememory-api-1 python scripts/memory_smoke.py --base-url http://127.0.0.1:8000 --output /tmp/cloud-acceptance.json`，截图显示 `status=passed`、`check_existing=false`、`result_count=3`。检查项包括 exact_echo、immediate_search_and_timestamp、retry_same_evidence、conflict_409、wrong_token_401、incremental_write、cross_session_evidence_role_and_top100、empty_other_user、api_process_recent_embedding_readiness。

此结果支持云端容器内真实模型与数据库的小样闭环通过。原始 JSON 目前保存在服务器容器 `/tmp/cloud-acceptance.json`，本机尚未获取；这里明确是用户截图观察，没有伪造本地原始报告。只有 3 条结果，不能证明满 100 条、大规模容量或重启持久化。截图同时显示 `platform_smoke=not_performed` 和数据库重复计数未由 HTTP 测量。

下文关于公网本地凭据 401 的历史结果仍有效：容器自己的配置通过不代表本地客户端凭据已同步，也不代表外网完整链路已验收。下一步通过 `http://aixuexi.asia` 运行同一容器内的 smoke，验证域名和 Nginx 路径；请求仍从服务器发起，须与独立外网验收分开记录。

2026-10-06 23:08 用户后续截图：容器执行 `memory_smoke.py --base-url http://aixuexi.asia --output /tmp/cloud-domain-acceptance.json` 同样返回 `status=passed`、`result_count=3`，全部 9 项检查通过。域名、Nginx 转发、正确与错误令牌、真实模型及数据库小样闭环在服务器发起的请求上通过。原始报告仍在服务器；此结果未证明独立外网正确凭据已同步、API 重启持久化或官方平台 Smoke。

2026-10-06 23:09 用户后续截图：执行 `docker restart tracememory-api-1` 后，通过域名运行 `memory_smoke.py --check-existing /tmp/cloud-domain-acceptance.json --output /tmp/cloud-restart-acceptance.json`，返回 `status=passed`、`check_existing=true`、`result_count=3`。检查项为跨会话来源/角色与 Top100 上限、空用户隔离、API 进程近期模型就绪。确认 API 容器重启后先前的小样仍可检索，未重新 Add；数据库未重启，未验证数据卷重建或灾难恢复，仍不是官方 Smoke。三份原始 JSON 尚在容器内，待复制到服务器宿主目录并下载核验。

- 全套本地回归共 79 项：71 通过、8 跳过、0 失败、0 错误，见 `verification.json`。真实数据库 7 项和付费向量模型 1 项在本轮没有启用，不能记为通过；旧运行证据单独保留。
- 重新审计既有真实模型 60 题开发集与 40 题留出集的逐题输出，数据及运行源码哈希匹配；各 cutoff 无来源错误和泄露。93 题有证据题 Recall@5=1.0；候选仅 25～49 块，不能推算官方成绩或大规模长期记忆效果。
- 经当前客户端默认代理配置：HTTP `/health` 返回 200/ok；公开 OpenAPI 含 Add/Search；两个接口使用故意错误令牌均返回 401。见 `public-http.json`。
- 禁用客户端代理时，本机到 HTTP 域名的连接失败。见 `public-direct.json`。这是该客户端路径的结果，不代表已确认平台或其他网络不可访问。
- 当前 `/ready/memory` 返回 503，配置和数据库迁移为 ok，embedding 为 not_probed_or_expired。代码确认这是 API 进程的近期模型调用缓存；独立 admin probe 不会更新此缓存，不能据此判定模型故障。
- 用程序加载已有本地配置尝试真实公网 Add，返回 401，完成检查数为 0。未读取或输出配置值。见 `public-memory-smoke.json`。线上未接受本次使用的凭据；尚不能确认具体是密钥不同还是中间链路影响。
- HTTPS 没有取得有效验收结果；Windows curl 检查遇到本地 Schannel 凭据错误，不把此错误当成远端证书不存在的证明。

证据目录：`docs/evidence/20261006-final-review/`。所有新证据另存，旧证据未覆盖。公网报告只收集公开响应、路径、状态码和哈希，不保存密钥；合成测试与官方平台评测明确区分。

## 本轮修正

新增无凭据公网检查脚本 `scripts/review_public_memory.py`，即使连接失败也保存报告；基础检查通过仍固定标记 `release_accepted=false`，防止把健康检查当成项目验收。

`scripts/memory_smoke.py` 现在同时保存失败记录、状态码、时间和 endpoint，不输出异常字符串、请求头或响应正文。新增测试验证连接失败、缺少鉴权、错误 schema 和失败报告脱敏。

新增 `deploy/accept-memory-server.sh`，使用服务器现有容器环境完成真实 Add/Search、Nginx 就绪与运行源码哈希收集；可选重启验证。此脚本尚未在服务器执行，不把脚本存在当成云端通过。

更新提交模板实际 HTTP 地址，修正申请指南中的许可、仓库与公网过时状态。没有为模型规则疑义增加 LLM 调用或改变已验证的检索流程。

## 尚未满足的发布与参赛条件

| 条件 | 结论及下一动作 |
|---|---|
| 云端真实模型闭环 | 用户最新截图显示容器内和域名路径小样均通过；服务器原始 JSON 待获取。独立外网闭环待验证 |
| 独立外网正确鉴权 | 未通过。安全同步最终 API 密钥到客户端配置，再运行公网 smoke，保存完整脱敏证据 |
| 重启与版本一致 | API 重启持久化小样经用户截图确认通过；运行文件哈希、最终镜像和申报 commit 一致性仍待核对 |
| 最终服务器容量 | 只有历史本机 1000 条串行样本。正式声明的并发、长请求、数据规模和模型配额仍需实测 |
| 公开仓库 | 本地公开快照 uploaded=false，主项目未配置 remote。若已人工上传，补真实 URL 与 commit 后验核 |
| 开源组别模型规定 | 官网 Full 检查项要求 Add 预期使用 gpt-4o-mini，通用架构说明又允许自选内部实现。当前无 LLM 的方法须确认适用性，不能擅自勾选符合 |
| 申请与官方 Smoke/Full | 本地记录未申请，无 Eval Key、官方 Job ID 或审核记录。代码与小样检查不能替代官方流程 |

浏览器控制工具两次连接 Edge/Workbench 失败，无法接管当前已登录的云端终端。没有尝试用自制浏览器协议、读取浏览器凭据或从截图获取密钥。此限制阻止了云端执行，不影响已完成的本地和公开 HTTP 检查。

下一条可在已登录的阿里云终端直接运行（使用旧镜像内已存在的脚本，不需上传新文件）：

```bash
sudo docker exec tracememory-api-1 python scripts/memory_smoke.py --base-url http://127.0.0.1:8000 --output /tmp/cloud-acceptance.json
```

该命令会进行少量自建合成数据写入和真实模型调用，打印不含密钥的结果。通过后仍须保存原始报告、外网正确鉴权、重启和固定版本验收。它不是要求用户重新审查全部项目，而是当前工具无法执行的最小服务器操作。

官方来源（本轮实时读取）：https://agentmemoryleaderboard.ai/api-guide 。平台要求自托管 Add/Search、固定版本与材料，获批后执行官方 Smoke/Full；开源方法另需公开仓库及来源披露。无需单独制作用户前端来实现这些接口接入条件。
