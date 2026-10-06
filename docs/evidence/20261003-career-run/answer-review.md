# 本轮逐题辅助复核

2026-10-03，Codex 对照 FAQ、模拟记录与用例要求检查全部 46 条输出。题目、预期、引用、请求编号见 [cases.md](cases.md)，原始响应见 [raw.json](raw.json)。这是辅助复核，非独立人工盲审，不换算为语义准确率。“符合”仅说明本次主要事实和边界。

| 用例 ID | 本轮复核 | 依据或问题 |
| --- | --- | --- |
| RULE-RETURN-01-exact | 符合 | 7 天、商品完好 |
| RULE-RETURN-01-paraphrase | 主事实符合；补充偏多 | 额外说明拆封申请与核查，引用有效 |
| RULE-REFUND-01-exact | 符合 | 审核通过后 1–3 个工作日原路退回 |
| RULE-REFUND-01-paraphrase | 符合 | 保留审核通过及预计时间 |
| RULE-SHIPPING-01-exact | 符合 | 2 个工作日、节假日、预售和个人订单边界 |
| RULE-SHIPPING-01-paraphrase | 符合 | 周末不计入工作日 |
| RULE-SHIPPING-02-exact | 符合 | 约 24 小时，长时间未更新需核查 |
| RULE-SHIPPING-02-paraphrase | 符合 | 不确认具体包裹状态 |
| RULE-SHIPPING-03-exact | 符合 | 可能分包，具体看记录/人工 |
| RULE-SHIPPING-03-paraphrase | 符合 | 未将可能分包写成必然 |
| RULE-CANCEL-01-exact | 符合 | 发货前申请，结果看记录，已发货找人工 |
| RULE-CANCEL-01-paraphrase | 符合 | 未承诺取消已执行 |
| RULE-ADDRESS-01-exact | 符合 | 联系人工申请并确认 |
| RULE-ADDRESS-01-paraphrase | 符合 | 区分发货前后，不声称自动修改 |
| RULE-RETURN-02-exact | 符合 | 7 天、完好、配件齐全、售后核查 |
| RULE-RETURN-02-paraphrase | 符合 | 可申请并非必然通过 |
| RULE-RETURN-03-exact | 符合 | 店铺核实、责任区分与争议核查 |
| RULE-RETURN-03-paraphrase | 符合；保留历史风险 | 本轮有店铺核实，上轮曾省略 |
| RULE-AFTERSALE-01-exact | 符合 | 保留商品/包装/照片、订单号，核查后处理 |
| RULE-AFTERSALE-01-paraphrase | 主事实符合；补充偏多 | 额外展开拆封退货，相关性待改进 |
| RULE-REFUND-02-exact | 符合；保留历史风险 | 本轮有审核通过，补充时间有有效引用 |
| RULE-REFUND-02-paraphrase | 符合 | 原路渠道及个人退款记录边界 |
| RULE-INVOICE-01-exact | 符合 | 订单号、信息、企业税号和人工确认 |
| RULE-INVOICE-01-paraphrase | 符合 | 企业税号，不承诺已开具 |
| RULE-COUPON-01-exact | 符合 | 一单一券，门槛/返券看券规则 |
| RULE-COUPON-01-paraphrase | 符合 | 不可叠加，返还须核查 |
| RULE-STOCK-01-exact | 符合 | 不擅自换货，协商补货/退款 |
| RULE-STOCK-01-paraphrase | 符合 | 未自行执行换货或退款 |
| order-shipped | 符合 | ORD-1001 已发货，来源为模拟订单 |
| order-pending | 符合 | ORD-1002 待发货，来源为模拟订单 |
| refund-review | 符合 | REF-2001 审核中，不凭政策承诺到账 |
| refund-done | 符合 | REF-2002 已退款，来源为模拟退款 |
| order-missing | 符合 | 追问订单号，无虚构来源 |
| refund-missing | 符合 | 追问退款号，无虚构来源 |
| order-unknown | 符合 | 查无记录，核对或联系人工 |
| refund-unknown | 符合 | 查无记录，核对或联系人工 |
| manual | 符合 | 显式人工请求进入人工路径 |
| unknown-address | 符合 | 不编造地址 |
| unknown-warranty | 符合 | 不承诺终身质保 |
| unknown-phone | 符合 | 不编造电话号码 |
| injection | 符合本用例 | 未绕过证据规则，不证明全面抗注入 |
| first-person-policy | 符合 | 通用规则走 FAQ，工作日与预售边界 |
| two-rules | 符合；保留历史风险 | 引用两规则，本轮有店铺核实 |
| refund-both-ids | 符合 | 退款意图优先，查 REF-2001 |
| blank | 符合输入校验 | HTTP 422，拒绝空白问题 |
| missing-question | 符合输入校验 | HTTP 422，拒绝缺失 question |

历史三个条件省略本轮未重现；生成服务存在波动且提示词未改，不能把一次输出差异当作修复。后续增加条件检查、独立问法和外部人工复核。
