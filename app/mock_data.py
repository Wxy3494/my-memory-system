# 以下均为教学用模拟数据，不是真实订单。
MOCK_ORDERS = {
    "ORD-1001": {
        "status": "已发货",
        "shipping_company": "模拟快递",
        "tracking_no": "MOCK-TRACK-001",
        "updated_at": "2026-09-25 10:00",
    },
    "ORD-1002": {
        "status": "待发货",
        "shipping_company": None,
        "tracking_no": None,
        "updated_at": "2026-09-25 11:00",
    },
}
MOCK_REFUNDS = {
    "REF-2001": {
        "status": "审核中",
        "amount_cents": 9900,
        "updated_at": "2026-09-25 12:00",
    },
    "REF-2002": {
        "status": "已退款",
        "amount_cents": 3500,
        "updated_at": "2026-09-25 13:00",
    },
}
MOCK_RULES = {
    "RULE-RETURN-01": {
        "title": "退货申请期限",
        "content": "签收后7天内可申请退货，商品须保持完好。",
        "keywords": ["退货", "退换"],
    },
    "RULE-REFUND-01": {
        "title": "退款到账时间",
        "content": "退款审核通过后，预计1至3个工作日原路退回。",
        "keywords": ["退款到账", "退款规则"],
    },
}