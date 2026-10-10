"""Rebuild 100 synthetic diagnostic questions; no external benchmark text used."""
import json
import argparse
from pathlib import Path


def reference(request_id, ordinal, quote):
    return dict(request_id=request_id, ordinal=ordinal, quote=quote)


def build(output_dir=None):
    cases = []
    cities = ["广州", "杭州", "南京", "厦门", "青岛"]
    for i in range(20):
        split = "dev" if i < 12 else "holdout"
        for kind in range(5):
            name = f"{split}-{i:02d}-{kind}"
            user = "user-" + name
            writes = []
            def add(request, session, messages, other=False):
                writes.append(dict(request_id=request, user_id=user + ("-other" if other else ""),
                                   session_id=session, messages=messages))
            message = lambda text, role="user", timestamp=None: dict(role=role, content=text, timestamp=timestamp)
            city = cities[i % len(cities)]
            code = f"TRACE-{3100 + i}"
            if kind == 0:
                english = i % 3 == 0
                text = f"My project access code is {code}." if english else f"我的项目访问编号是{code}，负责人叫小林。"
                add("fact", "work", [message(text)])
                query = "What is my project access code?" if english else "我的项目访问编号是什么？"
                refs = [reference("fact", 0, code)]
                category = "explicit_fact"
                answer = code
            elif kind == 1:
                add("chain-a", "one", [message(f"我的导师小林在{city}工作。")])
                add("chain-b", "two", [message("我的项目负责人就是我的导师小林。")])
                query = "我的项目负责人在哪个城市工作？请查找跨会话证据。"
                refs = [reference("chain-a", 0, city), reference("chain-b", 0, "我的导师小林")]
                category = "cross_session_multi_evidence"
                answer = city
            elif kind == 2:
                add("old", "jan", [message("一月份我通常周五下午开会。", timestamp=1704067200000)])
                add("new", "feb", [message("从二月起我把例会改到周二上午，旧安排不再使用。", timestamp=1706745600000)])
                query = "我的例会安排从一月到二月有什么变化？"
                refs = [reference("old", 0, "周五下午"), reference("new", 0, "周二上午")]
                category = "temporal_update"
                answer = {"一月": "周五下午", "二月": "周二上午"}
            elif kind == 3:
                add("same-id", "home", [message(f"我叫小林，现在住在{city}。")])
                add("same-id", "home", [message("我也叫小林，住在火星城。")], other=True)
                query = "我现在住在哪个城市？"
                refs = [reference("same-id", 0, city)]
                category = "user_isolation"
                answer = city
            else:
                if i % 3 == 0:
                    add("unknown", "hobby", [message("我喜欢阅读历史小说。")])
                    query, refs, category = "我养的宠物叫什么名字？", [], "no_answer"
                    answer = None
                elif i % 3 == 1:
                    long = ("这是一段与目标无关的练习文本，讨论天气和书架整理。\n" * 100) + f"最后补充：我的退款追踪编号是{code}。"
                    add("long", "customer", [message(long)])
                    query, refs, category = "我的退款追踪编号是多少？", [reference("long", 0, code)], "long_message"
                    answer = code
                else:
                    add("ellipsis", "calendar", [message("你愿意把本次会议安排在周四上午吗？", "assistant"),
                                                message("是的，按你说的安排。")])
                    query = "本次会议最终同意安排在什么时间？"
                    refs = [reference("ellipsis", 0, "周四上午"), reference("ellipsis", 1, "是的")]
                    category = "ellipsis_roles"
                    answer = "周四上午"
            # Same-user distractors make top-5 more meaningful; no-answer remains explicitly scored separately.
            add("noise", "other-notes", [message(f"资料{j}：我保存了一份{['烹饪', '植物', '电影', '登山'][j % 4]}笔记，标签N-{i}-{j}。") for j in range(24)])
            contract = dict(version="local-answer-v2", type="exact_json", expected=answer,
                            status="unknown" if answer is None else "answer")
            options = None
            if answer is not None and isinstance(answer, str) and i % 4 == 0:
                alternatives = ([f"TRACE-{3100+i+offset}" for offset in (1, 2, 3)] if answer.startswith("TRACE-")
                                else [s for s in (cities if answer in cities else ["周一上午", "周二下午", "周五下午"]) if s != answer][:3])
                choices = [answer, *alternatives]
                offset = i % len(choices)
                choices = choices[offset:] + choices[:offset]
                options = [f"{chr(65+j)}. {value}" for j,value in enumerate(choices)]
                contract.update(type="single_choice", expected=chr(65+choices.index(answer)))
                query += "请选择一个选项。"
            cases.append(dict(case_id=name, split=split, provenance="locally_synthetic_v2_not_official_gold",
                              category=category, writes=writes,
                              search=dict(user_id=user, query=query, top_k=100,
                                          options=options), answer_contract=contract,
                              acceptable_evidence_groups=[refs] if refs else []))
    root = Path(output_dir) if output_dir else Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "holdout"):
        path = root / f"memory_cases_v2_{split}.jsonl"
        path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cases if c["split"] == split), encoding="utf-8")
    return cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    print({"cases": len(build(args.output_dir)), "status": "generated_v2_preserving_v1"})
