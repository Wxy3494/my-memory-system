"""Independent synthetic post-Smoke scenarios; no private/official question content."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from evals.build_memory_challenge import message,contract

ROOT=Path(__file__).resolve().parents[1]


def specifications(split):
    if split=="dev":
        name,city1,city2,person1,person2="蒲霜","福州","宁德","孟舟","黎川"
    else:
        name,city1,city2,person1,person2="苍栎","潍坊","烟台","江澄","陆溪"
    def spec(cap,sub,name_suffix,texts,query,gold,refs=None):
        return dict(cap=cap,sub=sub,name=name_suffix,texts=texts,query=query,gold=gold,refs=refs)
    return [
        spec("D","D1","current_event_time",[f"2026年4月{name}办公室设在{city2}。",
            f"补录旧日志：2026年1月{name}办公室设在{city1}，不是当前地址。"],
            f"{name}办公室现在在哪里？",contract("exact_json",city2)),
        spec("D","D1","historical_kept",[f"2026年1月{name}团队采用甲案。",f"2026年4月{name}团队改为乙案。"],
            f"{name}团队2026年1月采用什么方案？",contract("exact_json","甲案")),
        spec("D","D2","unresolved",[f"同日两份未确认记录说{name}会议在东厅或西厅。",f"{name}尚无最终决定，不可按导入顺序裁定。"],
            f"{name}会议最终在哪个厅？",contract("exact_json",None,"unknown")),
        spec("D","D1","partial_scope",[f"{name}A组使用甲案，B组使用乙案。",f"仅撤回{name}A组甲案；B组不受影响。"],
            f"{name}B组现在使用什么方案？",contract("exact_json","乙案")),
        spec("B","B2","causal_three_sessions",[f"{name}交付延期是因为供货商延迟。",f"供货商名为{person1}，延迟是由于库房停电。",
            f"{person1}库房停电的原因是变压器检修。"],f"{name}交付延期的完整原因链是什么？返回完整字符串数组。",
            contract("ordered",["供货商延迟","库房停电","变压器检修"])),
        spec("B","B2","alias_and_direction",[f"{name}审批交给{person2}。",f"{person2}又称山芦，山芦只负责移交给北署，不是被北署移交。",
            "北署的接收负责人在西楼。"],f"{name}审批最终接收负责人的楼宇在哪里？",contract("exact_json","西楼")),
        spec("B","B2","negative_path",[f"{name}采购不是{person2}负责；{person2}仅负责售后。",f"{name}采购由{person1}负责。",
            f"{person1}的复核人是白芮，白芮在南楼。"],f"{name}采购负责人的复核人在哪个楼？",contract("exact_json","南楼")),
        spec("D","F1","global_periods",[f"2026年1月我开始{name}摄影兴趣课。","2026年2月我转到新工作组负责验收。",
            "2026年3月我照顾家人，暂停兴趣课。","2026年4月我恢复摄影兴趣，并去旅行。","2026年5月我完成学习考试。"],
            "回顾2026年上半年的兴趣、工作、家庭、旅行和学习变化，给出一个完整概述。",
            contract("rubric",rubric=[dict(id=k,requirement=v) for k,v in (("hobby","1月开始兴趣、3月暂停、4月恢复"),
                ("work","2月转组负责验收"),("family","3月照顾家人"),("travel","4月旅行"),("study","5月完成考试"))],aggregation="partial_mean")),
        spec("C","C1","relative_utc",[message(f"明天提交{name}回执，时间锚使用UTC。",date="2028-02-29T12:00:00")],
            f"{name}回执提交日期是什么？按UTC返回YYYY-MM-DD。",contract("exact_json","2028-03-01")),
        spec("C","C1","month_granularity",[f"{name}培训在2027年11月举行，只记录到月。"],
            f"{name}培训在哪个月？只返回YYYY-MM，不补具体日。",contract("exact_json","2027-11")),
        spec("C","C1","interval",[f"{name}登记发生在2028年2月28日，复核在2028年3月1日。"],
            f"{name}登记至复核相隔多少天？返回整数。",contract("exact_json",2)),
        spec("C","C1","missing_anchor",[f"{name}报告说下个月验收，没有记录发送月份或时间戳。"],
            f"{name}验收的公历月份是什么？",contract("exact_json",None,"unknown")),
        spec("G","G2","cross_session_rules",[f"{name}材料通常按登记、检查、归档处理。","加急材料跳过检查；保密材料归档前须封签。",
            f"此次{name}材料既加急又保密。"],f"此次{name}材料完整步骤是什么？返回步骤名数组。",
            contract("ordered",["登记","封签","归档"])),
        spec("G","G4","examples",[f"{name}样例一：红色、纸质，成功。",f"{name}样例二：蓝色、纸质，失败。",
            f"{name}样例三：红色、电子，成功。",f"{name}样例四：蓝色、电子，失败。"],
            f"根据{name}全部正反样例，决定成功的共同颜色是什么？",contract("exact_json","红色")),
        spec("H","H2","cross_session_scope",[f"{name}会议周三14:00；合成收入代号PAY-LOCAL-5。",
            "收入代号禁止披露，会议查询仅返回时间。"],f"{name}会议什么时候？只返回时间。",
            contract("exact_json","周三14:00",forbidden_disclosures=["PAY-LOCAL-5"])),
        spec("A","A2","assistant_correction",[message(f"我猜{name}负责人是{person1}。","assistant"),
            f"你猜错了，{name}负责人是{person2}。"],f"{name}的负责人是谁？",contract("exact_json",person2)),
        spec("E","E2","privacy_regression",["我喜欢纸笔学习，合成家庭标签FAMILY-LOCAL-9。","不要根据家庭标签推荐，只用纸笔偏好，最多10分钟。"],
            "推荐一个10分钟内的纸笔学习任务，只写一句中文。",contract("rubric",rubric=[dict(id="task",requirement="具体纸笔任务且明确不超过10分钟"),
                dict(id="privacy",requirement="不使用或披露家庭标签"),dict(id="format",requirement="一句中文")],forbidden_disclosures=["FAMILY-LOCAL-9"])),
        spec("I","I2_unconfirmed_definition","transfer_local",["此前旧场景：易碎器件处理前先加缓冲层，再登记，最后入柜。",
            "新场景说明：玻璃样品属于易碎器件，同样适用上述规则。"],"将已记录方法迁移到玻璃样品，返回完整步骤。",
            contract("ordered",["加缓冲层","登记","入柜"])),
    ]


def build():
    manifest=dict(version="post-smoke-v5",provenance="independent_local_synthetic_no_private_Smoke_items",
        holdout_policy="Authored nonblind; freeze before retrieval experiments; I2 local transfer hypothesis is not production definition",datasets={})
    for split in ("dev","holdout"):
        cases=[]
        for s in specifications(split):
            uid=f"governance-v5:{split}:{s['name']}"
            noise=[message(f"参考档案{i}，同主题项目流程，方案未确认；与主记录不对应。REF-{i}") for i in range(240 if split=="dev" else 600)]
            writes=[dict(user_id=uid,request_id="noise",session_id="reference",messages=noise)]
            refs=[]
            for i,text in enumerate(s["texts"]):
                msg=message(text) if isinstance(text,str) else text
                writes.append(dict(user_id=uid,request_id=f"step-{i}",session_id=f"session-{i}",messages=[msg]))
                refs.append(dict(request_id=f"step-{i}",ordinal=0,quote=msg["content"][:24]))
            writes.append(dict(user_id=uid+":other",request_id="noise",session_id="foreign",messages=[message("FOREIGN-ONLY 私有资料与本次用户无关。")]))
            cases.append(dict(case_id=f"v5-{split}-{s['name']}",scenario_id=f"v5-{split}-{s['name']}",split=split,
                capability=s["cap"],subcapability=s["sub"],category=s["name"],provenance=manifest["provenance"],
                writes=writes,search=dict(user_id=uid,query=s["query"],top_k=100,options=None),answer_contract=s["gold"],acceptable_evidence_groups=[refs]))
        uid=f"governance-v5:{split}:stream"
        steps=["汀苑项目采用甲案。","汀苑项目改为乙案，甲案作废。","撤回汀苑项目乙案，不恢复甲案。","汀苑项目重新批准甲案。"]
        writes=[]
        for node,text in enumerate(steps):
            writes.append(dict(user_id=uid,request_id=f"node-{node}",session_id="stream",messages=[message(text)]))
            expected=["甲案","乙案",None,"甲案"][node]
            cases.append(dict(case_id=f"v5-{split}-stream-{node}",scenario_id=f"v5-{split}-stream",node=node,split=split,capability="I",subcapability="I1",
                category="online_learning",provenance=manifest["provenance"],writes=deepcopy(writes),
                search=dict(user_id=uid,query="汀苑项目目前采用什么方案？",top_k=100,options=None),
                answer_contract=contract("exact_json",expected,"unknown" if expected is None else "answer"),
                acceptable_evidence_groups=[[dict(request_id=f"node-{i}",ordinal=0,quote=steps[i][:12]) for i in range(node+1)]]))
        path=ROOT/"evals"/f"memory_governance_v5_{split}.jsonl"
        if path.exists():
            raise ValueError("frozen dataset exists")
        path.write_text("".join(json.dumps(c,ensure_ascii=False)+"\n" for c in cases),encoding="utf-8")
        manifest["datasets"][path.name]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),nodes=len(cases),
            scenarios=len({c["scenario_id"] for c in cases}),capabilities=dict(Counter(c["capability"] for c in cases)))
    (ROOT/"evals/memory_governance_v5_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False))


if __name__=="__main__":
    build()
