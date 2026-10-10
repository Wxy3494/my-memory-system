# GitHub方法核验与适配记录

核验日期：2026-10-07，北京时间。先通过GitHub插件搜索仓库、搜索提交和源码，再读取固定commit的实现及LICENSE；GitHub公开API补充星数，因为插件的仓库结构未返回该字段。星数是当天读取快照，随时间变化，不作为效果证明。原始源码、blob SHA、固定URL、许可及取舍保存于 `evidence/20261007-round3/github-methods.json`。

| 参考项目 | 当日星数与核验入口 | 实际读取的固定commit | 作者/许可 |
|---|---|---|---|
| [LlamaIndex](https://github.com/run-llama/llama_index) | 52,425，[GitHub API](https://api.github.com/repos/run-llama/llama_index) | cb4c917ffe8ca575075b4869cf0e8bb42a20edb6 | Jerry Liu，MIT，已读取该commit的LICENSE |
| [LangChain](https://github.com/langchain-ai/langchain) | 147,522，[GitHub API](https://api.github.com/repos/langchain-ai/langchain) | f5a80b1b04cd4602573f3b35b99d457ba28b8dc9 | LangChain, Inc.，MIT，已读取该commit的LICENSE |

这些是本次实际读取的固定版本，不声称仍为仓库最新HEAD。两者均由`stars:>10000`的GitHub仓库搜索检索到，随后核验源码；没有只凭README作选择。

## 具体实现与取舍

1. [LlamaIndex句子窗口源码](https://github.com/run-llama/llama_index/blob/cb4c917ffe8ca575075b4869cf0e8bb42a20edb6/llama-index-core/llama_index/core/node_parser/text/sentence_window.py)：`build_window_nodes_from_documents`将文本分成句子节点，为节点附周边句子窗口，并保留original_text。采用“小块用于定位、关联上下文补证”的思路；不改变现有无损分块、稳定ID、Embedding输入或数据库signature。
2. [LlamaIndex内容替换源码](https://github.com/run-llama/llama_index/blob/cb4c917ffe8ca575075b4869cf0e8bb42a20edb6/llama-index-core/llama_index/core/postprocessor/metadata_replacement.py)：`_postprocess_nodes`可以将节点内容替换成metadata窗口。没有采用直接替换或拼接多条消息的方法，因为本项目要求逐条原文切片、角色、时间和偏移均可审计；改为返回不同来源的独立原文片段。
3. [LangChain父文档源码](https://github.com/langchain-ai/langchain/blob/f5a80b1b04cd4602573f3b35b99d457ba28b8dc9/libs/langchain/langchain_classic/retrievers/parent_document_retriever.py)：`_split_docs_for_adding`建立child与parent的ID关系，分别存储。采用“命中child后定位parent”的层次思路；现有memory.messages就是父消息，chunk_sources已提供关系，复用现有表而不引入新框架。
4. [LangChain多向量源码](https://github.com/langchain-ai/langchain/blob/f5a80b1b04cd4602573f3b35b99d457ba28b8dc9/libs/langchain/langchain_classic/retrievers/multi_vector.py)：`_get_relevant_documents`检索child，按首次出现顺序去重parent ID，再取父文档；另有MMR分支。采用按父消息去重、保持来源秩序和分配预算的思路。没有照搬全文父文档返回，避免超出32KiB预算；没有引入需新语义模型的MMR或示例中的模型默认值。

## 本地实现

运行代码独立编写，不复制上游函数、不安装这两套框架。参考源码快照的完整MIT声明保留在同一证据JSON内，NOTICE披露来源。仍使用指定的text-embedding-v4/1024维配置；本轮不调用付费Embedding或Answer/Judge。

`PostgresStore.neighbors`先按同用户/会话的接收顺序定位父消息，再逐消息读取文本块，不读取向量。`message_candidates`为每个父消息选最多8个片段：问题词项、词项差异较大的片段、头/中/尾，以及同一消息中的种子位置。跨消息的字符偏移不再用于推断相关性。应用每种子最多扩展8块、每消息每种子最多6块，保留种子条数/字节预留和限量交错，最终TopK/32KiB约束仍生效。

词项差异是局部词项分布指标，不是语义模型。头中尾采样也不是全文覆盖；若事实在其他位置且没有可区别的词项，仍可能漏检。父消息扫描成本随文本块数增长；一次只处理一个父消息，限制返回候选不意味着扫描耗时固定。单个Add仍受原有8MiB/20000块保护，大历史语料和1GiB云服务器仍需实测。

同分BM25/RRF优先按来源session/request/ordinal/offset与内容摘要排序，公共namespace前缀不影响这些来源字段的相对次序；向量SQL的同分顺序也先比较session/request/content。模型无关的source顺序用于稳定性，不能把顺序本身当作冲突的语义答案。

## 实测而非星数决定交付

最终隔离数据库：111项测试=110通过/1付费探测跳过；86节点全部完成，有限金标的complete@5/@20/@100均100%、来源审计和跨用户泄露0。原冲突题与六个长文位置情境，在五组namespace下的原文Top20顺序一致，全部complete@5=100%。原反例的新相关情境覆盖头、中、尾、四分之一、四分之三及英文改写；保持原种子预算/多会话三跳/不足预算回归。详细成本与局限见三轮整改报告。
