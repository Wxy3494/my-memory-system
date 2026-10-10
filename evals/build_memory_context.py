"""Versioned gold annotations plus independent positional/implicit local scenarios."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from evals.memory_eval import load_cases
from evals.build_memory_challenge import contract, message

ROOT = Path(__file__).resolve().parents[1]


def build():
    inputs = [ROOT/"evals"/f"{suite}_{split}.jsonl" for suite in ("memory_challenge_v2", "memory_stress_v3")
              for split in ("dev", "holdout")]
    cases = deepcopy(load_cases(inputs))
    for case in cases:
        if case["answer_contract"]["status"] == "unknown" and not case["acceptable_evidence_groups"]:
            support = []
            for write in case["writes"]:
                if write["user_id"] != case["search"]["user_id"]:
                    continue
                for i,m in enumerate(write["messages"]):
                    if "没有记录" in m["content"] or "没有保存" in m["content"]:
                        support.append(dict(request_id=write["request_id"], ordinal=i, quote=m["content"]))
            case["evidence_annotations"] = dict(unknown_support=support, irrelevant=[])
    for split in ("dev", "holdout"):
        for i,position in enumerate(("head", "middle", "tail", "quarter", "three_quarters", "english_tail")):
            uid = f"context-v4:{split}:{position}"
            token = f"ULTRA-{split.upper()}-{i}"
            anchor = f"{token}：结论见紧接着发送的下一条说明。"
            if position == "english_tail":
                anchor = f"{token}: the next note identifies the coordinator and the destination."
                fact = "The coordinator is Mira and the destination is Oslo." if split == "dev" else "The coordinator is Theo and the destination is Perth."
                quotes = ["Mira", "Oslo"] if split == "dev" else ["Theo", "Perth"]
                query = f"For {token}, who coordinates the handover and where will it arrive?"
            else:
                fact = "最终负责人为陶宁，工作地为厦门。" if split == "dev" else "承办联系人为贺溪，驻地为太原。"
                quotes = ["陶宁", "厦门"] if split == "dev" else ["贺溪", "太原"]
                query = f"{token} 后续结论？给出负责人和城市的完整数组。"
            filler = "例行无关记录abcdefgh。" * 4000
            fraction = dict(head=0,middle=.5,tail=1,quarter=.25,three_quarters=.75,english_tail=1)[position]
            cut = int(len(filler)*fraction)
            long = filler[:cut] + fact + filler[cut:]
            noise = [message(f"其他登记{i}，REFERENCE-{i}，周二常规流程，与交接结论无关。") for i in range(240 if split == "dev" else 600)]
            writes = [dict(user_id=uid,session_id="other",request_id="noise",messages=noise),
                      dict(user_id=uid,session_id="main",request_id="anchor",messages=[message(anchor)]),
                      dict(user_id=uid,session_id="main",request_id="detail",messages=[message(long)]),
                      dict(user_id=uid+":other",session_id="main",request_id="anchor",messages=[message("FOREIGN-PRIVATE 无关的另一个用户结论。")])]
            cases.append(dict(case_id=f"v4-{split}-{position}",scenario_id=f"v4-{split}-{position}",
                split=split,capability="B",category="implicit_long_message",provenance="authored_nonblind_v4_not_official",
                writes=writes,search=dict(user_id=uid,query=query,top_k=100,options=None),
                answer_contract=contract("exact_json",quotes),
                acceptable_evidence_groups=[[dict(request_id="anchor",ordinal=0,quote=token),
                    *[dict(request_id="detail",ordinal=0,quote=q) for q in quotes]]]))
    manifest = dict(version="context-v4", upstream_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        holdout_policy="Authored nonblind; frozen before experiments; all outcomes retained", datasets={})
    for split in ("dev", "holdout"):
        path = ROOT/"evals"/f"memory_context_v4_{split}.jsonl"
        if path.exists():
            raise ValueError("frozen output already exists")
        selected = [c for c in cases if c["split"] == split]
        path.write_text("".join(json.dumps(c,ensure_ascii=False)+"\n" for c in selected),encoding="utf-8")
        manifest["datasets"][path.name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),nodes=len(selected),
            independent_scenarios=len({c["scenario_id"] for c in selected}),capabilities=dict(Counter(c["capability"] for c in selected)))
    (ROOT/"evals/memory_context_v4_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(manifest,ensure_ascii=False))


if __name__ == "__main__":
    build()
