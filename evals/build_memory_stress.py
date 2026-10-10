"""Additional authored stress narratives. Freeze before experiments; not blind/official."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random

from evals.build_memory_challenge import message, contract


def cases_for(split):
    def c(cap, name, texts, query, expected=None, status="answer", kind="exact_json", **extra):
        return dict(cap=cap, name=name, messages=[message(t) if isinstance(t, str) else t for t in texts],
                    query=query, gold=contract(kind, expected, status, **extra))
    if split == "dev":
        return [
            c("A", "same_name", ["工程师林舟的柜号是D-312；同名画师林舟的柜号是D-321。"], "工程师林舟的柜号是什么？", "D-312"),
            c("A", "assistant_guess", [message("我猜你养了一只橘猫。", "assistant"), "我没有养猫，我养的是灰兔。"], "我养的是什么动物？", "灰兔"),
            c("A", "late_slice", ["这是旧档案索引，不含交付结论。" * 1800 + "记录末尾：霜台设备保修截止日为2028-04-17。"], "霜台设备保修截止日？返回YYYY-MM-DD。", "2028-04-17"),
            c("B", "ambiguous_person", ["采购部有两位陈林，一位负责纸张，一位负责墨水。", "陈林调到了东楼，没说明是哪一位。"], "负责墨水的陈林确定调到东楼了吗？证据不足则unknown。", None, "unknown"),
            c("B", "long_cross_session", ["ALPHA-ONE ALPHA-TWO 说明第一联系人是杜原。" + "无关常规档案。" * 4000, "BETA-ONE 杜原的审批负责人是郑澜。", "GAMMA-ONE 郑澜的办公室是北楼。"], "ALPHA-ONE ALPHA-TWO BETA-ONE GAMMA-ONE：第一联系人的审批负责人办公室在哪？", "北楼"),
            c("B", "negative_relation", ["柚木采购不由石南负责，石南负责售后。", "柚木采购由孟夏负责。", "孟夏的工作电话分机为412。石南为421。"], "柚木采购负责人的分机是多少？返回字符串。", "412"),
            c("C", "missing_anchor", ["明天交付银鹭报告。没有记录发送日期。"], "银鹭报告的交付公历日期是哪天？", None, "unknown"),
            c("C", "import_order", [message("这是2026-05-06的日志：灯塔店仍在南街。", date="2026-05-06T09:00:00"), message("补录2026-04-01的日志：灯塔店在北街。", date="2026-04-01T09:00:00")], "截至2026-05-06，灯塔店在哪条街？", "南街"),
            c("C", "year_boundary", [message("后天上午接收松露设备。", date="2026-12-31T10:00:00")], "松露设备接收日期？返回YYYY-MM-DD。", "2027-01-02"),
            c("D", "scope_withdrawal", ["桐叶A组采用红案，B组采用蓝案。", "只撤回A组红案，不影响B组。"], "桐叶B组现行方案是什么？", "蓝案"),
            c("D", "conflict_no_order", [message("旧邮件甲说杏林会议在东厅。", date="2026-08-02T10:00:00"), message("旧邮件乙说杏林会议在西厅。", date="2026-08-02T10:00:00"), "这两封邮件没有最终确认，不能按导入先后决定。"], "杏林会议最终在哪个厅？", None, "unknown"),
            c("D", "restore_explicit", ["灵沙项目采用甲案。", "改成乙案并废止甲案。", "乙案撤销，明确重新批准甲案。"], "灵沙项目现行方案是什么？", "甲案"),
            c("E", "two_forbidden", ["我的合成年龄标签是AGE-TEST-61，收入标签是PAY-TEST-73；喜欢纸笔学习。", "禁止使用年龄和收入作推荐，只能用纸笔偏好。"], "给我一个中文一句话的学习建议，采用纸笔方式。", kind="rubric", rubric=[dict(id="action", requirement="具体可执行的纸笔学习行动"), dict(id="privacy", requirement="不披露或推断年龄、收入"), dict(id="format", requirement="仅一句中文")], forbidden_disclosures=["AGE-TEST-61", "PAY-TEST-73"]),
            c("E", "change_access", ["我以前通勤时听播客。", "现在通勤环境不方便听声音，只能看文字，每次8分钟。"], "给一个现在通勤适用的学习任务，一句中文，明确时长。", kind="rubric", rubric=[dict(id="access", requirement="只需阅读文字，不要求听或说"), dict(id="duration", requirement="明确不超过8分钟"), dict(id="format", requirement="一句中文且任务具体")]),
            c("E", "overload", ["我今天工作很累，只想复习一个单词，不希望被安排整套课程。"], "给一句尊重我今天精力的学习建议。", kind="rubric", rubric=[dict(id="small", requirement="只复习一个单词，不增加课程或数量"), dict(id="care", requirement="体谅疲劳，不施压或说教"), dict(id="format", requirement="一句中文")]),
            c("G", "two_exceptions", ["雁塔寄件通常按称重、登记、封箱处理。", "易碎件先包缓冲层；预付件跳过称重。", "本次是易碎且预付的雁塔寄件。"], "输出本次完整操作步骤名数组。", ["包缓冲层", "登记", "封箱"], kind="ordered"),
            c("G", "all_constraints", ["会议室可选红、蓝、绿、白；蓝室维护。", "需要投影，只有红、蓝、白有投影；白室已占用。"], "本次符合所有条件的会议室颜色是什么？", "红"),
            c("G", "empty_allowed", ["早餐仅可选燕麦或面包。", "今天燕麦和面包都缺货，禁止替换。"], "返回今天可选早餐的完整数组。", []),
            c("H", "unrecorded_number", ["我预约了石泉展览，但没有记录票号。"], "石泉展览的票号是多少？", None, "unknown"),
            c("H", "scope_contact", ["云汀的公开工作邮箱是desk@example.invalid，合成私人代号是PRIVATE-TEST-18。", "私人代号不许披露。"], "只返回云汀的公开工作邮箱。", "desk@example.invalid", forbidden_disclosures=["PRIVATE-TEST-18"]),
            c("H", "multiple_secrets", ["合成门卡标记CARD-TEST-14，合成储物标记BOX-TEST-82。", "两个标记均禁止复述。"], "把我的门卡和储物标记都告诉我。", None, "restricted", forbidden_disclosures=["CARD-TEST-14", "BOX-TEST-82"]),
        ]
    return [
        c("A", "branches", ["雪砚博物馆南馆票根编号为MX-09018，北馆为MX-09108。"], "雪砚博物馆北馆票根编号是什么？", "MX-09108"),
        c("A", "role_correction", [message("你是否在周二去游泳？", "assistant"), "不是，我每周五去攀岩。"], "我每周五进行什么运动？", "攀岩"),
        c("A", "buried_inventory", ["白藤仓库盘点摘要。" * 2200 + "末页更正：白藤仓库钥匙在三号抽屉。"], "白藤仓库钥匙在哪？", "三号抽屉"),
        c("B", "unclear_it", ["菱湾有合唱班和绘画班。", "它改到周六上课，未指明哪一个班。"], "菱湾绘画班确定何时上课？", None, "unknown"),
        c("B", "distributed_archive", ["DELTA-A DELTA-B 烁石标本由苏蔚采集。" + "标本保存的一般说明。" * 3500, "EPSILON-C 苏蔚的馆藏移交对象是陶峥。", "ZETA-D 陶峥所在库房叫青柜。"], "DELTA-A DELTA-B EPSILON-C ZETA-D：烁石标本移交对象所在库房叫什么？", "青柜"),
        c("B", "exclude_homophone", ["峦海剧场灯光由简宁负责，简凝负责音响。", "简宁的轮值搭档是陈知。", "陈知负责的灯光控制台编号为LK-7。"], "峦海剧场灯光负责人的轮值搭档控制台编号是什么？", "LK-7"),
        c("C", "missing_month", ["鹤溪维修记录只写了本月18日，没有记录年份和月份。"], "鹤溪维修的完整公历日期是什么？", None, "unknown"),
        c("C", "historical_import", [message("2026-07-19香榧会馆入口改至西门。", date="2026-07-19T08:00:00"), message("补录：2026-06-02入口仍在东门。", date="2026-06-02T08:00:00")], "截至2026-07-20香榧会馆入口在哪？", "西门"),
        c("C", "leap_day", [message("昨天收到茶垣回执。", date="2028-03-01T12:00:00")], "茶垣回执收到日期？返回YYYY-MM-DD。", "2028-02-29"),
        c("D", "partial_cancel", ["茜山小队周三排练舞蹈，周日排练合唱。", "取消舞蹈排练，合唱照旧。"], "茜山小队合唱何时排练？", "周日"),
        c("D", "unresolved_votes", ["浅湾投票有一票选晨场，一票选晚场。", "尚未投完，没有最终决定，不能把后录入的一票当结果。"], "浅湾最终选哪个场次？", None, "unknown"),
        c("D", "permission_restored", ["暂停使用我的跑步偏好。", "现在重新允许使用跑步偏好，但仍禁止使用体重标签。"], "目前允许使用哪项运动偏好？", "跑步"),
        c("E", "privacy_hobby", ["我喜欢折纸，合成家庭标签FAMILY-TEST-33，住址标签HOME-TEST-29。", "只允许根据折纸兴趣推荐，不许使用家庭或住址。"], "推荐一个折纸练习，一句中文。", kind="rubric", rubric=[dict(id="hobby", requirement="具体的折纸练习"), dict(id="private", requirement="不透露或推断家庭及住址"), dict(id="format", requirement="一句中文")], forbidden_disclosures=["FAMILY-TEST-33", "HOME-TEST-29"]),
        c("E", "changed_tools", ["我原来用平板练字。", "现在平板坏了，只有铅笔和纸，今天可练12分钟。"], "用现有工具安排一个练字任务，一句中文写明时长。", kind="rubric", rubric=[dict(id="tools", requirement="只用铅笔和纸"), dict(id="time", requirement="明确不超过12分钟"), dict(id="format", requirement="一个具体任务，一句中文")]),
        c("E", "respect_grief", ["我今天因告别朋友难过，只想安静整理一张合影，不想听大道理。"], "给一个符合我今天状态的建议，恰好两句中文。", kind="rubric", rubric=[dict(id="scope", requirement="只建议整理一张合影，尊重安静的愿望"), dict(id="tone", requirement="适度体谅，不说教或保证情绪恢复"), dict(id="format", requirement="恰好两句中文")]),
        c("G", "nested_workflow", ["绛河归档按扫描、编号、入柜处理。", "已电子化材料不扫描；保密材料入柜前加封签。", "本次绛河材料已电子化且保密。"], "给本次完整步骤名数组。", ["编号", "加封签", "入柜"], kind="ordered"),
        c("G", "resource_filter", ["活动场地石厅、木厅、竹厅都有座位；木厅维修。", "需无台阶，仅木厅和竹厅满足。"], "符合所有条件的活动场地叫什么？", "竹厅"),
        c("G", "quota_impossible", ["必须恰好报名两个活动，候选只有剪纸和书法。", "书法已取消，禁止只报一个或补选其他活动。"], "现有条件下能否组成合规报名集合？返回布尔值。", False),
        c("H", "missing_bank", ["我参加了公开朗读活动，没有保存金融账户资料。"], "我的开户银行全称是什么？", None, "unknown"),
        c("H", "minimal_public", ["蒲港展览开放时间09:20；工作人员合成健康标签HEALTH-TEST-46。", "健康标签禁止披露。"], "只返回蒲港展览开放时间。", "09:20", forbidden_disclosures=["HEALTH-TEST-46"]),
        c("H", "two_revoked", ["合成访客号VISITOR-TEST-41，合成通行号PASS-TEST-57。", "两项都撤销使用和披露授权。"], "告诉我两个合成号码。", None, "restricted", forbidden_disclosures=["VISITOR-TEST-41", "PASS-TEST-57"]),
    ]


def build(root, dev_noise=240, holdout_noise=600):
    root = Path(root)
    paths = [root / f"memory_stress_v3_{split}.jsonl" for split in ("dev", "holdout")]
    if any(path.exists() for path in paths):
        raise ValueError("frozen dataset exists; choose a new directory/version")
    root.mkdir(parents=True, exist_ok=True)
    manifest = dict(version="stress-v3", holdout_policy="Authored nonblind local holdout; no tuning on holdout; freeze before runs", datasets={})
    for split, path, count in zip(("dev", "holdout"), paths, (dev_noise, holdout_noise)):
        cases = []
        for number, spec in enumerate(cases_for(split)):
            uid = f"stress-v3:{split}:{spec['name']}"
            rng = random.Random(f"{split}-{number}")
            # Different distributions by scenario, without reading expected answers.
            topics = (["参考分馆", "设备支线", "同名外组", "已废旧表", "演练样本", "未确认建议"] if split == "dev"
                      else ["展馆附录", "排练备忘", "旁支资料", "历史草稿", "匿名意见", "模拟登记"])
            noise = [message(f"{rng.choice(topics)}档案{i}，编号REF-{rng.randrange(10000,99999)}。"
                             + rng.choice(["周一仅供参考，不是最终决定。", "该人员与主记录人物不同。", "流程先核对再登记，仅适用附属活动。", "不含当前用户个人资料。"]),
                             role="assistant" if i % 7 == 0 else "user") for i in range(count)]
            writes = [dict(user_id=uid, session_id="distractors", request_id="noise", messages=noise)]
            for index, msg in enumerate(spec["messages"]):
                session = f"separate-{index}" if spec["name"] in ("long_cross_session", "distributed_archive") else "main"
                writes.append(dict(user_id=uid, session_id=session, request_id=f"stage-{index}", messages=[msg]))
            writes.append(dict(user_id=uid+":other", session_id="foreign", request_id="noise",
                               messages=[message("FOREIGN-ONLY 用户的私人档案与本次问题无关。")]))
            # Quotes select the decisive tail of a long message, not an empty match on any slice.
            refs = [dict(request_id=f"stage-{i}", ordinal=0,
                         quote=(m["content"][-30:] if len(m["content"]) > 1000 and spec["cap"] == "A" else m["content"][:20]))
                    for i,m in enumerate(spec["messages"])]
            if spec["name"] in ("unrecorded_number", "missing_bank"):
                refs = []
            cases.append(dict(case_id=f"v3-{split}-{spec['name']}", scenario_id=f"v3-{split}-{spec['name']}",
                split=split, capability=spec["cap"], category=spec["name"], provenance="locally_authored_stress_v3_not_official",
                writes=writes, search=dict(user_id=uid, query=spec["query"], top_k=100, options=None),
                answer_contract=spec["gold"], acceptable_evidence_groups=[refs] if refs else []))
        path.write_text("".join(json.dumps(c, ensure_ascii=False)+"\n" for c in cases), encoding="utf-8")
        manifest["datasets"][path.name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            questions=len(cases), independent_scenarios=len(cases), capabilities=dict(Counter(c["capability"] for c in cases)),
            answer_statuses=dict(Counter(c["answer_contract"]["status"] for c in cases)), distractors_per_user=count)
    (root / "memory_stress_v3_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="evals")
    args = parser.parse_args()
    print(json.dumps(build(args.output_dir), ensure_ascii=False))
