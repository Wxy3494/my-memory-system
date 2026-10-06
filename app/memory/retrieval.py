import json
import re

from .schemas import Evidence, Source


def keyword_terms(query):
    terms = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", query.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", query):
        terms.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            terms.append(run)
    # Optional bounded lexical path; vector path always represents the full query.
    return list(dict.fromkeys(terms))[:128]


def rank(vector_rows, lexical_rows, top_k, hybrid=False):
    if not hybrid:
        return vector_rows[:top_k]
    scores, rows = {}, {}
    for route in (vector_rows, lexical_rows):
        for position, row in enumerate(route, 1):
            key = row["chunk_id"]
            scores[key] = scores.get(key, 0) + 1 / (60 + position)
            rows[key] = row
    return [dict(rows[key], score=scores[key]) for key in
            sorted(scores, key=lambda key: (-scores[key], key))[:top_k]]


def evidence(row):
    sources = [Source(**{key: value[key] for key in Source.model_fields}) for value in row["sources"]]
    # Source times are not ingestion times or inferred event dates. Preserve role.
    labels = [dict(role=s.role, timestamp_ms=s.timestamp, session_id=s.session_id,
                   ordinal=s.ordinal, start_offset=s.start_offset, end_offset=s.end_offset) for s in sources]
    prefix = "[source " + json.dumps(labels, ensure_ascii=False, separators=(",", ":")) + "]\n"
    return Evidence(id=row["chunk_id"], content=prefix + row["content"],
                    score=float(row["score"]), sources=sources)
