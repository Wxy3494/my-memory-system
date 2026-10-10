import json
import math
import re
import hashlib
from datetime import datetime, timezone
from collections import Counter

from .schemas import Evidence, Source


def keyword_terms(query):
    terms = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", query.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", query):
        terms.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            terms.append(run)
    # Optional bounded lexical path; vector path always represents the full query.
    return list(dict.fromkeys(terms))[:128]


def lexical_tokens(text):
    """Latin identifiers + CJK bigrams; preserve term frequency for BM25."""
    tokens = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.extend(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1:
            tokens.append(run)
    return tokens


def source_order(row):
    """A common namespace prefix cannot change ordering of source identifiers."""
    source = row.get("sources", [row])[0]
    return (source.get("session_id", row.get("session_id", "")),
            source.get("request_id", row.get("request_id", "")),
            source.get("ordinal", row.get("ordinal", 0)),
            source.get("start_offset", row.get("start_offset", 0)),
            hashlib.sha256(row.get("content", "").encode()).hexdigest())


def message_candidates(rows, terms=(), anchors=()):
    """Child -> parent -> eight bounded raw candidates, independently implemented.

    Query relevance and lexical novelty locate interior facts; structural samples
    provide head/middle/tail coverage without a paid model. This is no guarantee
    of semantic relevance for every arbitrary interior fragment.
    """
    rows = sorted(rows, key=lambda r: (r["start_offset"], source_order(r)))
    if not rows:
        return []
    counts = [Counter(lexical_tokens(r["content"])) for r in rows]
    df = Counter(t for count in counts for t in count)
    novelty = [sum(math.log(1 + len(rows)/df[t]) for t in count) / math.sqrt(sum(count.values()) or 1)
               for count in counts]
    unusual = sorted(range(len(rows)), key=lambda i: (-novelty[i], rows[i]["start_offset"]))[:2]
    relevant = bm25_rank(rows, terms, 2)
    near = [min(rows, key=lambda r: abs(r["start_offset"]-offset)) for offset in anchors[:2]]
    head, middle, tail = rows[0], rows[len(rows)//2], rows[-1]
    candidates = [*relevant[:1], *[rows[i] for i in unusual[:1]], head, middle, tail,
                  *relevant[1:], *[rows[i] for i in unusual[1:]], *near]
    selected = {}
    for row in candidates:
        if row["chunk_id"] not in selected:
            selected[row["chunk_id"]] = dict(row, neighbor_priority=len(selected))
        if len(selected) == 8:
            break
    return list(selected.values())


def bm25_rank(rows, terms, limit, k1=1.2, b=0.75):
    if not rows or not terms:
        return []
    counts = [Counter(lexical_tokens(row["content"])) for row in rows]
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / len(rows) or 1
    document_frequency = Counter(t for c in counts for t in c)
    ranked = []
    for row, count, length in zip(rows, counts, lengths, strict=True):
        score = 0.0
        for term in set(terms):
            frequency = count[term]
            if frequency:
                df = document_frequency[term]
                idf = math.log(1 + (len(rows)-df+0.5)/(df+0.5))
                score += idf * frequency * (k1+1) / (frequency+k1*(1-b+b*length/average))
        if score > 0:
            ranked.append(dict(row, score=score))
    return sorted(ranked, key=lambda row: (-row["score"], source_order(row)))[:limit]


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
            sorted(scores, key=lambda key: (-scores[key], source_order(rows[key])))[:top_k]]


def combine_context(selected,context):
    first,extra,seen=[],[],set()
    for row in context:
        mid=row["sources"][0]["message_id"]
        (extra if mid in seen else first).append(row); seen.add(mid)
    output,ids=[],set()
    # Preserve the tested direct/neighbor prefix; supplementation must not
    # demote strong direct evidence merely because a lexical hint matched.
    for row in selected[:5]+first+extra+selected[5:]:
        if row["chunk_id"] not in ids:
            output.append(dict(row,score=1/(len(output)+1))); ids.add(row["chunk_id"])
    return output


def evidence(row):
    sources = [Source(**{key: value[key] for key in Source.model_fields if key in value}) for value in row["sources"]]
    # Source times are not ingestion times or inferred event dates. Preserve role.
    labels = [dict(role=s.role, timestamp_ms=s.timestamp, session_id=s.session_id,
                   ordinal=s.ordinal, start_offset=s.start_offset, end_offset=s.end_offset) for s in sources]
    for label, source in zip(labels, sources, strict=True):
        if source.timestamp is not None:
            try:
                anchor=datetime.fromtimestamp(source.timestamp/1000,timezone.utc).isoformat()
            except (ValueError,OverflowError,OSError):
                anchor=None
            label.update(message_time_utc=anchor,time_metadata_version="utc-anchor-v1")
        if source.received_ordinal is not None:
            label.update(request_id=source.request_id, received_ordinal=source.received_ordinal,
                         stored_at=source.stored_at, order_basis=source.order_basis,
                         time_semantics="timestamp_ms=message_time; stored_at=ingestion_time; event_time=raw_text")
    prefix = "[source " + json.dumps(labels, ensure_ascii=False, separators=(",", ":")) + "]\n"
    return Evidence(id=row["chunk_id"], content=prefix + row["content"],
                    score=float(row["score"]), sources=sources)


def expand_neighbors(seeds, neighbors, window, top_k=100, byte_budget=0):
    """Reserve seeds, then fairly interleave bounded raw neighbors.

    At most six extra chunks per message and eight per seed. Scores in this
    expanded route describe selection order, not cosine similarity. Whole source
    slices (including provenance headers) count against the byte reservation.
    """
    reserved, seed_ids, sizes = [], set(), {}
    remaining_bytes = byte_budget
    for seed in seeds:
        if seed["chunk_id"] in seed_ids or len(reserved) == top_k:
            continue
        size = len(evidence(seed).content.encode("utf-8"))
        if byte_budget and size > remaining_bytes:
            continue
        reserved.append(seed)
        seed_ids.add(seed["chunk_id"])
        sizes[seed["chunk_id"]] = size
        remaining_bytes -= size
    queues = []
    for seed in reserved:
        related = []
        for row in neighbors:
            if row["user_id"] != seed["user_id"] or row["chunk_id"] in seed_ids:
                continue
            distances = [abs(a["received_ordinal"]-b["received_ordinal"])
                         for a in seed["sources"] for b in row["sources"]
                         if a.get("received_ordinal") is not None and b.get("received_ordinal") is not None
                         and a["session_id"] == b["session_id"]]
            if distances and min(distances) <= window:
                # Character offsets only relate within the SAME message.
                offset = min((abs(a["start_offset"]-b["start_offset"])
                              for a in seed["sources"] for b in row["sources"]
                              if a["message_id"] == b["message_id"]), default=0)
                related.append((min(distances) == 0, min(distances),
                                row.get("neighbor_priority", 0), offset, source_order(row), row))
        counts, queue = Counter(), []
        for *_, row in sorted(related, key=lambda item: item[:5]):
            messages = {(s["session_id"], s["message_id"]) for s in row["sources"]}
            if any(counts[key] >= 6 for key in messages):
                continue
            queue.append(row)
            counts.update(messages)
            if len(queue) == 8:
                break
        queues.append(queue)
    output, seen, used = [], set(), 0
    pending_size = sum(sizes.values())

    def append(row):
        nonlocal used
        # Strictly decreasing rank utility makes the interleaved order explicit.
        output.append(dict(row, score=1.0 / (len(output) + 1)))
        seen.add(row["chunk_id"])
        used += len(evidence(row if "score" in row else dict(row, score=0)).content.encode("utf-8"))

    def add_one(queue, pending_count):
        for row in queue[:]:
            queue.remove(row)
            if row["chunk_id"] in seen:
                continue
            size = len(evidence(dict(row, score=0)).content.encode("utf-8"))
            if len(output) + pending_count >= top_k:
                return
            if byte_budget and used + pending_size + size > byte_budget:
                continue
            append(row)
            return

    for index, seed in enumerate(reserved):
        pending_size -= sizes[seed["chunk_id"]]
        append(seed)
        add_one(queues[index], len(reserved) - index - 1)
    # Round robin prevents any first message from consuming the remaining slots.
    while any(queues) and len(output) < top_k:
        for queue in queues:
            add_one(queue, 0)
    return output


def select_evidence(rows, top_k, byte_budget=0):
    output, used = [], 0
    for row in rows:
        item = evidence(row)
        size = len(item.content.encode("utf-8"))
        if byte_budget and used+size > byte_budget:
            continue  # Whole auditable slices only; never silently truncate source text.
        output.append(item)
        used += size
        if len(output) == top_k:
            break
    return output
