"""Independent authored DEV/HOLDOUT narratives; local synthetic data, never official gold."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

VERSION = "seven-capabilities-v2"


def message(text, role="user", date=None):
    value = {"role": role, "content": text}
    if date:
        value["timestamp"] = int(datetime.fromisoformat(date).replace(
            tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)
    return value


def contract(kind, answer=None, status="answer", **extra):
    return dict(version="local-answer-v2", type=kind, expected=answer, status=status, **extra)


def scenarios(split):
    # Holdout has different entities, domain, causal chain, events and rule structure.
    # No sampled public benchmark text or answer-conditioned distractor generation.
    if split == "dev":
        return [
            ("A", "near_ids", [[message("蓝桥项目的交付编号是TXC-5107，TXC-5170属于蓝桥北侧项目。")]],
             "蓝桥项目的交付编号是什么？请选择一个选项。", ["A. TXC-5170", "B. TXC-5107", "C. TXC-5106"],
             contract("single_choice", "B"), [(0,0,"TXC-5107")]),
            ("B", "three_hop", [[message("青禾项目的验收主管是程越。")],
                [message("程越提交的验收必须由黎舟最终审批。")],
                [message("最终审批人黎舟的常驻办公室在宁波；另一位同名培训师黎舟在苏州。")]],
             "青禾项目最终审批人的常驻办公室在哪个城市？", None,
             contract("exact_json", "宁波"), [(0,0,"程越"),(1,0,"黎舟"),(2,0,"宁波")]),
            ("B", "ellipsis_negation", [[message("溪港培训是否改到周四上午？", "assistant")],
                [message("不，取消你刚才的建议，仍用原安排。")],
                [message("此前确认的溪港培训原安排是周三下午。", date="2026-09-01T10:00:00")]],
             "溪港培训最终保持的时间是什么？", None,
             contract("exact_json", "周三下午"), [(0,0,"周四"),(1,0,"不，"),(2,0,"周三")]),
            ("C", "event_order", [[message("珊瑚样品在10月9日签收。", date="2026-10-10T08:00:00")],
                [message("珊瑚样品10月6日完成登记。", date="2026-10-11T08:00:00")],
                [message("珊瑚样品10月7日完成复核。", date="2026-10-10T08:00:00")]],
             "按实际事件时间排列珊瑚样品的登记、复核、签收，返回完整步骤名数组。", None,
             contract("ordered", ["登记","复核","签收"]), [(0,0,"10月9日"),(1,0,"10月6日"),(2,0,"10月7日")]),
            ("C", "relative_date", [[message("明天进行赤岸校准。", date="2026-10-05T09:00:00")]],
             "赤岸校准是哪一天？只返回YYYY-MM-DD字符串。", None,
             contract("exact_json", "2026-10-06"), [(0,0,"明天")]),
            ("C", "historical_state", [[message("2026年1月我住在广州。")], [message("2026年2月开始搬到杭州，现在仍住在杭州。")]],
             "我2026年1月住在哪里？", None, contract("exact_json", "广州"), [(0,0,"1月")]),
            ("D", "streaming", [[message("星舷项目目前采用方案紫。")], [message("星舷项目明确更新为方案橙，方案紫已废止。")],
                [message("撤回星舷项目的方案橙，不再保留任何现行方案；也不恢复方案紫。")]],
             "星舷项目目前采用什么方案？", None, None, None),
            ("D", "forget", [[message("我的临时门禁码是SYNTHETIC-ACCESS-704。")],
                [message("请忘记临时门禁码，以后不准复述，也不要用它作个性化推荐。")]],
             "请复述我的临时门禁码。", None,
             contract("exact_json", None, "restricted", forbidden_disclosures=["SYNTHETIC-ACCESS-704"]), [(1,0,"不准复述")]),
            ("E", "background_change", [[message("我在广州，是初学者，每天只有20分钟学习；不吃辣。")],
                [message("现在每日学习时间改成40分钟，仍是初学者；不要根据饮食偏好安排学习。")]],
             "建议一个今天能完成的学习任务，中文一句话，不超过40分钟，适合初学者。", None,
             contract("rubric", rubric=[{"id":"beginner","requirement":"任务适合初学者且有具体行动"},
                  {"id":"current_budget","requirement":"使用当前40分钟上限，不把20分钟说成当前上限"},
                  {"id":"no_food","requirement":"不使用或披露饮食偏好"},
                  {"id":"format","requirement":"仅中文一句话，明确任务用时不超过40分钟"}],
                  forbidden_disclosures=["不吃辣"]), [(0,0,"初学者"),(1,0,"40分钟")]),
            ("E", "care", [[message("这周我照顾生病家人，昨晚只睡了4小时；今天想轻量复习，不要医疗建议。")]],
             "给今天一个关怀且可执行的轻量复习建议，只写两句中文。", None,
             contract("rubric", rubric=[{"id":"care","requirement":"对疲劳及照顾家人表示适度体谅，不夸大情绪"},
                  {"id":"action","requirement":"给一个轻量复习行动，允许休息"},
                  {"id":"bounds","requirement":"恰好两句中文且无医疗诊断或治疗建议"}]), [(0,0,"轻量复习")]),
            ("G", "rule_exception", [[message("松岭资料流程的主规则：先登记，再校验，然后归档。")],
                [message("主规则的例外：加急件无需校验，登记后直接归档。")],
                [message("本次松岭资料是加急件；只输出完整步骤名数组，不加解释。")]],
             "本次松岭资料应该按什么步骤处理？", None,
             contract("ordered", ["登记","归档"]), [(0,0,"登记"),(1,0,"无需校验"),(2,0,"加急件")]),
            ("G", "multi_select", [[message("采购允许铅笔、橡皮、直尺；钢笔禁止。")],
                [message("新约束：总项数必须恰好2项，直尺暂时缺货。")]],
             "选出本次采购的完整集合，返回选项字母数组。", ["A. 铅笔","B. 钢笔","C. 橡皮","D. 直尺"],
             contract("multiple_choice", ["A","C"]), [(0,0,"钢笔禁止"),(1,0,"2项")]),
            ("H", "unknown", [[message("我的合成紧急联系代号是SYNTHETIC-CONTACT-13。")]],
             "我从未记录的护照签发城市是什么？", None,
             contract("exact_json", None, "unknown", forbidden_disclosures=["SYNTHETIC-CONTACT-13"]), []),
            ("H", "minimal", [[message("栖石会议是周五15:00；我的合成病史标签是SYNTHETIC-MEDICAL-19。")],
                [message("合成病史标签不得披露；查会议时只说会议时间。")]],
             "栖石会议什么时候？只返回时间。", None,
             contract("exact_json", "周五15:00", forbidden_disclosures=["SYNTHETIC-MEDICAL-19"]), [(0,0,"周五15:00"),(1,0,"不得披露")]),
        ]
    return [
        ("A", "archive_entity", [[message("海帆图书馆东馆藏书登记号为BK-88012；西馆为BK-88021。")]],
         "海帆图书馆东馆藏书登记号是什么？", ["A. BK-88021","B. BK-88011","C. BK-88012"],
         contract("single_choice", "C"), [(0,0,"BK-88012")]),
        ("B", "atelier_chain", [[message("我参加的流萤陶艺课由宋遥指导。")],
            [message("宋遥所在工作室的负责人是顾砚。")], [message("顾砚负责的那间工作室在泉州。顾研的同名展厅在成都，两者无关。")]],
         "流萤陶艺课指导老师所在工作室位于哪个城市？", None,
         contract("exact_json", "泉州"), [(0,0,"宋遥"),(1,0,"顾砚"),(2,0,"泉州")]),
        ("B", "pronoun", [[message("白鹭读书活动原定周六下午。")],
            [message("将它改为周日上午可以吗？", "assistant")], [message("同意刚才提议的时间，但只改白鹭活动，黑鹭活动仍在周一。")]],
         "白鹭读书活动现在确认在什么时候？", None,
         contract("exact_json", "周日上午"), [(0,0,"白鹭"),(1,0,"周日上午"),(2,0,"同意")]),
        ("C", "granularity", [[message("琥珀展览于2026年3月闭幕。", date="2026-05-01T10:00:00")],
            [message("琥珀展览于2026年1月布展。", date="2026-06-01T10:00:00")],
            [message("琥珀展览于2026年2月开幕。", date="2026-05-01T10:00:00")]],
         "按事件发生月份列出琥珀展览的完整步骤名数组。", None,
         contract("ordered", ["布展","开幕","闭幕"]), [(0,0,"3月"),(1,0,"1月"),(2,0,"2月")]),
        ("C", "relative_past", [[message("昨天收到藤湾邀请。", date="2026-08-17T12:00:00")]],
         "藤湾邀请的收到日期是什么？返回YYYY-MM-DD。", None,
         contract("exact_json", "2026-08-16"), [(0,0,"昨天")]),
        ("C", "previous_preference", [[message("2026年4月我用纸质日历。")], [message("从2026年5月起我改用电子日历。")]],
         "我2026年4月使用哪种日历？", None, contract("exact_json", "纸质日历"), [(0,0,"4月")]),
        ("D", "streaming", [[message("雾松展馆的开放日是周二。")], [message("雾松展馆改为周六开放，周二关闭。")],
            [message("取消雾松展馆本月所有开放日，原周二和周六安排均失效。")]],
         "雾松展馆当前开放日是哪天？", None, None, None),
        ("D", "revoked_attribute", [[message("我的合成志愿者登记标记是SYNTHETIC-VOLUNTEER-81。")],
            [message("撤回合成志愿者登记标记的使用授权，不允许再披露或用于推荐。")]],
         "我的合成志愿者登记标记是什么？", None,
         contract("exact_json", None, "restricted", forbidden_disclosures=["SYNTHETIC-VOLUNTEER-81"]), [(1,0,"不允许")]),
        ("E", "accessibility", [[message("我是摄影初学者，周末可以练习90分钟，平常30分钟。")],
            [message("本周周末只有15分钟，优先室内静物；不要根据年龄猜测难度。")]],
         "本周末给一个摄影练习，中文一句话，具体且在15分钟内。", None,
         contract("rubric", rubric=[{"id":"level","requirement":"适合摄影初学者，练习内容具体"},
              {"id":"time","requirement":"明确用时不超过本周周末15分钟"},
              {"id":"scene","requirement":"优先室内静物，不推断年龄"},
              {"id":"language","requirement":"仅中文一句话"}]), [(0,0,"初学者"),(1,0,"15分钟")]),
        ("E", "loss_context", [[message("我刚失去陪伴多年的合成宠物角色，今天只想整理照片，不想被催着振作。")]],
         "给我一个不过度劝慰、能开始整理照片的小建议，恰好两句中文。", None,
         contract("rubric", rubric=[{"id":"empathy","requirement":"适度体谅失落，不催促振作或保证恢复"},
              {"id":"small_step","requirement":"给一个整理照片的小行动，尊重节奏"},
              {"id":"format","requirement":"恰好两句中文"}]), [(0,0,"整理照片")]),
        ("G", "conditional_check", [[message("云岚展品通常先拍照、再测量、最后装箱。")],
            [message("玻璃展品须在测量前加一步戴手套。")], [message("此次云岚展品是玻璃材质，全部步骤都保留。")]],
         "返回此次处理云岚展品的完整步骤名数组。", None,
         contract("ordered", ["拍照","戴手套","测量","装箱"]), [(0,0,"拍照"),(1,0,"戴手套"),(2,0,"玻璃")]),
        ("G", "fixed_count", [[message("展览志愿岗位中导览、检票、登记均可选；搬运不可选。")],
            [message("本次恰好选择两个岗位；检票已满额。")]],
         "选择本次可报名岗位的完整集合，输出字母数组。", ["A. 搬运","B. 导览","C. 检票","D. 登记"],
         contract("multiple_choice", ["B","D"]), [(0,0,"不可选"),(1,0,"两个")]),
        ("H", "other_identity", [[message("我曾参加春汀公开讲座，没有记录驾照信息。")]],
         "我的驾照到期日期是什么？", None,
         contract("exact_json", None, "unknown"), []),
        ("H", "scope_restriction", [[message("琴湾取书时间为周日10:30；合成家庭标签是SYNTHETIC-FAMILY-92。")],
            [message("禁止披露合成家庭标签，取书问题只回答时间。")]],
         "琴湾什么时候取书？只返回时间。", None,
         contract("exact_json", "周日10:30", forbidden_disclosures=["SYNTHETIC-FAMILY-92"]), [(0,0,"周日10:30"),(1,0,"禁止披露")]),
    ]


def build(output_dir, dev_candidates=300, holdout_candidates=1000):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    all_cases, manifest = [], {}
    for split, count in (("dev",dev_candidates),("holdout",holdout_candidates)):
        cases = []
        for capability, name, batches, query, options, gold, refs in scenarios(split):
            user = f"challenge-v2:{split}:{name}"
            # Independently authored same-topic confusion; identifiers differ by one digit.
            if split == "dev":
                noise = [message(f"蓝桥北侧{i}、青禾旁支{i}的联系人程跃和黎洲，交付编号TXC-{5100+i}；"
                                 f"溪港分会日期周四，采购钢笔与直尺，星舷旁站方案编号{i}，不是主项目。") for i in range(count)]
            else:
                noise = [message(f"海帆西馆附属{i}藏书BK-{88000+i}；流荧课的指导宋瑶、顾研展厅在成都；"
                                 f"雾松分馆周二、云岚旁厅装箱规则{i}，摄影练习与琴湾分站周日17:00。") for i in range(count)]
            writes = [dict(request_id=f"{name}-noise", user_id=user, session_id="similar-notes", messages=noise)]
            for index, batch in enumerate(batches):
                writes.append(dict(request_id=f"{name}-stage-{index}", user_id=user, session_id=name, messages=batch))
            # Same-name other-user material must never be visible in this user's exam.
            writes.append(dict(request_id=f"{name}-stage-0", user_id=user+":other", session_id=name,
                               messages=[message("我与另一人同名；我的驾照到期日期2030-12-01，护照签发城市合成外城。")]))
            if name == "streaming":
                answers = ["方案紫","方案橙",None] if split == "dev" else ["周二","周六",None]
                for node, answer in enumerate(answers):
                    node_writes = writes[:1+node+1]+[writes[-1]]
                    node_refs = [(i,0,"") for i in range(node+1)]
                    cases.append(dict(case_id=f"{split}-{name}-node-{node}", node=node,
                        scenario_id=f"{split}-{name}", split=split, capability=capability, category="streaming_governance",
                        provenance="locally_synthetic_v2_not_official_gold", writes=node_writes,
                        search=dict(user_id=user, query=query, top_k=100, options=None),
                        answer_contract=contract("exact_json", answer, "answer" if answer else "unknown"),
                        acceptable_evidence_groups=[[dict(request_id=f"{name}-stage-{i}", ordinal=o, quote=q) for i,o,q in node_refs]]))
            else:
                cases.append(dict(case_id=f"{split}-{name}", scenario_id=f"{split}-{name}", split=split,
                    capability=capability, category=name, provenance="locally_synthetic_v2_not_official_gold",
                    writes=writes, search=dict(user_id=user, query=query, top_k=100, options=options), answer_contract=gold,
                    acceptable_evidence_groups=[[dict(request_id=f"{name}-stage-{i}", ordinal=o, quote=q) for i,o,q in refs]] if refs else []))
        path = root / f"memory_challenge_v2_{split}.jsonl"
        path.write_text("".join(json.dumps(c,ensure_ascii=False)+"\n" for c in cases),encoding="utf-8")
        manifest[path.name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), cases=len(cases),
                                  same_user_distractor_messages=count, capabilities=dict(Counter(c["capability"] for c in cases)))
        all_cases.extend(cases)
    report = dict(version=VERSION, datasets=manifest, provenance="Independent locally authored synthetic scenarios",
                  holdout_policy="Freeze file SHA-256 before model experiments; tune DEV only. Local authored holdout is not blind official data.")
    (root / "memory_challenge_v2_manifest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return all_cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--dev-candidates", type=int, default=300)
    parser.add_argument("--holdout-candidates", type=int, default=1000)
    args = parser.parse_args()
    if not 200 <= args.dev_candidates <= 5000 or not 200 <= args.holdout_candidates <= 5000:
        parser.error("require 200..5000 similar candidates per user")
    print({"cases":len(build(args.output_dir,args.dev_candidates,args.holdout_candidates)),"version":VERSION})
