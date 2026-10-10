# 原始工作披露与 v6 方法说明

2026-10-10。我以 Wxy3494 署名发布“我的记忆系统”（内部名称 TraceMemory），采用 MIT 许可。原客服 RAG 项目和后续记忆服务改造都使用了 AI 辅助，下面说明我参考的工作和具体实现。所用检索方法包含已有工作。

## 原工程与个人实现

我从同一仓库的客服 RAG 工程扩展记忆服务，沿用了 FastAPI 服务组织、SQL 和脱敏监控。原公开基线为 [142f0dd](https://github.com/Wxy3494/my-memory-system/commit/142f0ddcdd2ccc06b044c47f2777a99d3b3707e9)，署名 Wxy3494；我保留了这段提交历史。原 FAQ/BGE/DeepSeek 路径保留用于溯源，参赛入口 app.memory_main:app。

我在 AI 辅助下完成的记忆服务实现与改动如下：

- app/memory/chunking.py：UTF-8 预算无损分块、稳定 ID、原文偏移和角色/时间/session 来源。
- store.py 与迁移 001～004：同步事务、幂等、用户隔离、跨 Add 接收顺序、邻近索引与来源线索存储。
- retrieval.py/service.py：向量与词项排名、可选 BM25/RRF、邻近消息/父消息扩展及证据预算，返回可审计原文。
- signals.py：词项关联和保守事件日期作用域、当前状态排序、历史时段分组；不把相对时间、计划、控制语句或不确定关联强行裁定为事实。线索只帮助检索，不是最终答案。
- tests 和 evals/build_memory_*.py：协议、失败路径、来源审计及自建合成情境。样本为非盲开发诊断，不属于官方题库或官方成绩。

我把已有检索思想组合到原文记忆服务中。这是工程实现，尚未证明它优于参考工作，也没有提出新的通用算法。技术说明见本固定 commit 源码、docs/memory-design.md 和 docs/github-methods-20261007.md；带日期文档中的旧结果属于历史记录。

## 参考仓库、原作者与改动

1. LlamaIndex：Jerry Liu 及 contributors，MIT。固定 commit [cb4c917ffe8ca575075b4869cf0e8bb42a20edb6](https://github.com/run-llama/llama_index/tree/cb4c917ffe8ca575075b4869cf0e8bb42a20edb6)。技术资料：[句子窗口源码](https://github.com/run-llama/llama_index/blob/cb4c917ffe8ca575075b4869cf0e8bb42a20edb6/llama-index-core/llama_index/core/node_parser/text/sentence_window.py)、[内容替换源码](https://github.com/run-llama/llama_index/blob/cb4c917ffe8ca575075b4869cf0e8bb42a20edb6/llama-index-core/llama_index/core/postprocessor/metadata_replacement.py)、[LICENSE](https://github.com/run-llama/llama_index/blob/cb4c917ffe8ca575075b4869cf0e8bb42a20edb6/LICENSE)。我参考了小片段定位后补充上下文的思路，按同用户/会话/接收顺序定位消息，返回各自带来源的独立原文块，保留预算，不以窗口文本替换原块。
2. LangChain：LangChain, Inc. 及 contributors，MIT。固定 commit [f5a80b1b04cd4602573f3b35b99d457ba28b8dc9](https://github.com/langchain-ai/langchain/tree/f5a80b1b04cd4602573f3b35b99d457ba28b8dc9)。技术资料：[父文档检索源码](https://github.com/langchain-ai/langchain/blob/f5a80b1b04cd4602573f3b35b99d457ba28b8dc9/libs/langchain/langchain_classic/retrievers/parent_document_retriever.py)、[多向量检索源码](https://github.com/langchain-ai/langchain/blob/f5a80b1b04cd4602573f3b35b99d457ba28b8dc9/libs/langchain/langchain_classic/retrievers/multi_vector.py)、[LICENSE](https://github.com/langchain-ai/langchain/blob/f5a80b1b04cd4602573f3b35b99d457ba28b8dc9/LICENSE)。我参考了 child 命中后定位并去重 parent 的思路，复用 messages/chunk_sources，父消息内选片并限量交错，不直接返回整个父文档，不引入框架、示例默认模型或 MMR。

上述版本在既有 2026-10-07 核验记录中读取。我参考的是设计思路，运行代码没有安装这两套框架，也没有复制其函数。方法取舍技术报告是 docs/github-methods-20261007.md；原本地审计快照保留在历史证据树，不随本次导出上传。

## 论文与经典方法

Gordon V. Cormack、Charles L. A. Clarke、Stefan Büttcher（2009），**Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods**，SIGIR '09，758–759，[DOI 10.1145/1571941.1572114](https://doi.org/10.1145/1571941.1572114)，[作者论文](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)。我在可选的 hybrid_bm25 中使用 1/(60+rank) 累加排名思想，自行处理用户隔离、来源排序、原文扩展与预算；线上截图为 vector，不将实验 RRF 描述成线上默认配置。

我采用的 BM25 是已有词项排名方法；本地参数、分词与候选策略以 retrieval.py 为准，我的实现没有复现论文中的实验结果。

## 依赖、许可与公开范围

FastAPI/Pydantic、httpx、NumPy、Prometheus client、psycopg、pgvector、python-dotenv 以及 PostgreSQL/Python/Debian/Caddy 分别属于原项目作者与维护者。我的项目使用这些依赖，其实现属于各自的原作者和维护者；版本及许可见 third-party-dependencies.md。本项目 MIT 不替代组件原许可。

我从公开仓库中排除了实际环境文件、密钥、数据库转储、官方私有题目/答案和评测输出，只在公开副本清除历史私有编号。本地原件仍然保留。自建 gold 位于测试/自测目录，运行服务不读取它们生成答案；我没有用任务编号给运行排序添加特例。
