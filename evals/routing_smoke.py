"""新增问法回归；辅助编写，非独立盲测。不会覆盖 46 题基线。"""
import json,sys
from pathlib import Path
from run import call
CASES=[
 ('policy-weekend',{'question':'我想咨询现货发货安排，周日计入工作日吗？'},'faq_rag',False,'RULE-SHIPPING-01'),
 ('policy-presale',{'question':'请告诉我预售商品发货时间以什么为准？'},'faq_rag',False,'RULE-SHIPPING-01'),
 ('personal-purchase',{'question':'我购买的商品发货了吗？'},'order_lookup',False,'请提供订单号'),
 ('refund-associated-order',{'question':'请查退款进度，谢谢','order_id':'ORD-1002','refund_id':'REF-2002'},'refund_lookup',False,'已退款'),
 ('refund-no-order',{'question':'我的订单的退款状态如何？','refund_id':'REF-2001'},'refund_lookup',False,'审核中'),
 ('refund-missing',{'question':'我的订单退款进度如何？','order_id':'ORD-1002'},'refund_lookup',False,'请提供退款单号'),
 ('refund-unknown',{'question':'退款状态请查一下','order_id':'ORD-1002','refund_id':'REF-404'},'handoff',True,'未查到模拟退款'),
 ('order-both',{'question':'请查订单进度','order_id':'ORD-1002','refund_id':'REF-2002'},'order_lookup',False,'待发货'),
]
results=[]
for id,payload,route,human,required in CASES:
    actual=call('http://127.0.0.1:8000',payload)
    b=actual['body']
    passed=actual['status']==200 and b.get('route')==route and b.get('needs_human') is human and required in (b.get('answer','')+' '.join(b.get('sources',[])))
    results.append(dict(id=id,payload=payload,expected_route=route,required=required,actual=actual,passed=passed))
Path(sys.argv[1]).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'total':len(results),'passed':sum(r['passed'] for r in results)}))
sys.exit(0 if all(r['passed'] for r in results) else 1)
