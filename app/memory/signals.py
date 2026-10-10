"""Source-linked lexical hints, never authoritative facts or generated answers."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import math
import re

from .retrieval import keyword_terms

VERSION = "source-lexical-signals-v2"
DATE = re.compile(r"(?P<year>20\d{2})(?:年|[-/])(?P<month>\d{1,2})(?:(?:月|[-/])(?P<day>\d{1,2})日?|月)?")
BOUNDARY = re.compile(r"[。；;\n，,！？!?]+|(?:同时|另有|此外|并且|随后|后来|而|但|且|并)(?=\s*20\d{2}(?:年|[-/]))")
ATTRIBUTE = re.compile(r"采用|使用|住在|位于|设在|负责人是|负责人为|开放日是|开放日为")
FACT = re.compile(r"^\s*(.{1,40}?)"+"("+ATTRIBUTE.pattern+")")
RELATIVE = re.compile(r"今天|昨天|明天|后天|本月|上个月|去年|tomorrow|yesterday", re.I)
FUTURE = re.compile(r"计划|预计|拟|将|预约|预定|planned|intend|\bwill\b", re.I)
OPS = {"update":r"改为|改成|更新|变更|现在|从.*起|changed|updated",
       "withdraw":r"撤回|取消|废止|不再|作废|withdraw|cancel|revoke",
       "restore":r"重新批准|重新允许|恢复|restore|reinstate",
       "conflict":r"未确认|未决定|没有最终|没有记录|未说明|尚未|unconfirmed|not decided",
       "privacy":r"禁止.*(?:披露|复述|使用)|不准|不许|不要根据|不得|授权|private|do not disclose",
       "rule":r"规则|必须|只有|须|例外|禁止|恰好|步骤|流程|rule|must|unless|except",
       "example":r"例如|样例|示例|成功|失败|案例|经验|example|succeeded|failed",
       "causal":r"因为|由于|导致|所以|因此|原因|because|caused|resulted",
       "alias":r"又称|别名|简称|也叫|alias|also called"}
TOPICS = {"work":r"项目|工作|交付|审批|客户|work|project", "study":r"学习|课程|考试|复习|study|course",
          "family":r"家人|家庭|孩子|照顾|family", "health":r"健康|疲劳|睡眠|health|sleep",
          "travel":r"旅行|出差|旅程|travel|trip", "hobby":r"兴趣|摄影|运动|琴|跑步|陶艺|hobby|sport"}


def utc_anchor(timestamp):
    try:
        return datetime.fromtimestamp(timestamp/1000, timezone.utc).isoformat() if timestamp is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def _dates(text, offset):
    result=[]
    for match in DATE.finditer(text):
        y,m,d=int(match["year"]),int(match["month"]),int(match["day"] or 1)
        try:
            datetime(y,m,d)
        except ValueError:
            continue
        result.append(dict(raw=match[0],start=offset+match.start(),end=offset+match.end(),
            precision="day" if match["day"] else "month",sort=y*10000+m*100+(d if match["day"] else 0)))
    return result


def _scopes(text, offset, original):
    """Do not turn a lexical sampling cut into an invented sentence boundary."""
    begin=0
    for boundary in BOUNDARY.finditer(text):
        if boundary.start()>begin:
            if begin or not offset or original[offset-1] in "。；;\n，,！？!?":
                yield offset+begin,offset+boundary.start()
        begin=boundary.end()
    if begin<len(text) and offset+len(text)==len(original):
        if begin or not offset or original[offset-1] in "。；;\n，,！？!?":
            yield offset+begin,offset+len(text)


def _binding(fragment, start, timestamp):
    dates=_dates(fragment,start)
    relatives=list(RELATIVE.finditer(fragment))
    binding=dict(status="unknown",event_span=[start,start+len(fragment)],expressions=dates,
                 sort=None,reason="no_explicit_scoped_date")
    if relatives:
        binding.update(reason="relative_date_unresolved",anchor_utc=utc_anchor(timestamp))
    # Multiple dates, temporal references, or predicates in one unsplit clause
    # have no safe fact-level date. Keep the raw clause for downstream interpretation.
    if len(list(DATE.finditer(fragment)))>1 or (dates and relatives) or len(list(ATTRIBUTE.finditer(fragment)))>1:
        binding["reason"]="ambiguous_multiple_events_or_times"
        return binding
    if not dates:
        return binding
    date=dates[0]
    prefix=fragment[:date["start"]-start]
    allowed_prefix=re.fullmatch(r"\s*(?:(?:补录[^：:]{0,20}[：:]|截至|从|自|在|于)\s*)*",prefix)
    fact=FACT.search(fragment)
    subject_time=bool(fact and date["end"]-start<=fact.start(2)
                      and re.search(r"(?:在|于)\s*$",prefix))
    if allowed_prefix or subject_time:
        binding.update(status="explicit_scoped_date",sort=date["sort"],reason="date_in_source_event_scope")
    else:
        binding["reason"]="date_role_or_scope_unconfirmed"
    return binding


def _subject(raw):
    subject=re.sub(r"^(?:补录[^：:]{0,20}[：:]\s*)?", "", raw.strip())
    first=DATE.match(subject)
    if first:
        subject=subject[first.end():].strip()
    for date in reversed(list(DATE.finditer(subject))):
        prefix=subject[:date.start()]
        if not subject[date.end():].strip() and re.search(r"(?:在|于)\s*$",prefix):
            subject=re.sub(r"(?:在|于)\s*$","",prefix).strip()
    subject=re.sub(r"^(?:目前|现在|当前|恢复允许|恢复|重新允许|撤回|取消|计划|预计|拟|将)\s*","",subject)
    return re.sub(r"(?:目前|现在|当前|不再|计划|预计|拟|将)\s*$","",subject).strip()


def _bounded(items,limit):
    # Spread retained source spans across the bounded samples, including both ends.
    if len(items)<=limit:
        return items
    if limit==1:
        return items[-1:]
    return [items[i*(len(items)-1)//(limit-1)] for i in range(limit)]


def extract(text, role="user", timestamp=None):
    # Bounded lexical samples; whole original text is retained and hashed separately.
    starts=sorted({0,max(0,len(text)//2-2048),max(0,len(text)-4096)})
    terms,expressions,events,seen_fragments=[],[],{},set()
    for start in starts:
        sample=text[start:start+4096]
        terms.extend(keyword_terms(sample))
        expressions.extend(_dates(sample,start))
        for begin,end in _scopes(sample,start,text):
            if (begin,end) in events:
                continue
            fragment=text[begin:end]
            if fragment in seen_fragments:
                continue
            seen_fragments.add(fragment)
            operations=[k for k,p in OPS.items() if re.search(p,fragment,re.I)]
            kind=("prospective" if FUTURE.search(fragment) else "control_or_unresolved" if
                  set(operations)&{"withdraw","restore","conflict"} else "statement")
            binding=_binding(fragment,begin,timestamp)
            match=FACT.search(fragment)
            topics=[k for k,p in TOPICS.items() if re.search(p,fragment,re.I)]
            if not (match or binding["expressions"] or RELATIVE.search(fragment) or operations or topics):
                continue
            event=dict(start=begin,end=end,time_binding=binding,claim_kind=kind,
                       terms=keyword_terms(fragment)[:128],topics=topics,operations=operations)
            fact=None
            if match:
                subject=_subject(match[1])
                value_start=begin+match.end(); value_end=min(end,value_start+128)
                if subject and value_end>value_start:
                    fact=dict(subject=subject,attribute=match[2],value=text[value_start:value_end],
                        start=value_start,end=value_end,event_span=[begin,end],time_binding=binding,
                        claim_kind=kind,authority="user" if role=="user" else "assistant")
            events[(begin,end)]=(event,fact)
        for match in RELATIVE.finditer(sample):
            expressions.append(dict(raw=match[0],start=start+match.start(),end=start+match.end(),
                precision="relative",anchor_utc=utc_anchor(timestamp),resolved=False))
    sample="\n".join(text[s:s+4096] for s in starts)
    template=re.sub(r"\d+","#",sample[:512].lower())
    retained=[]
    def priority(pair):
        event,fact=pair
        return 0 if fact or event["time_binding"]["expressions"] or event["time_binding"].get("anchor_utc") else 1 if event["operations"] else 2
    for level in range(3):
        group=sorted((p for p in events.values() if priority(p)==level),key=lambda p:p[0]["start"])
        budget=96-len(retained)
        if budget:
            retained.extend(_bounded(group,budget))
    retained.sort(key=lambda p:p[0]["start"])
    facts=_bounded([fact for _,fact in retained if fact],32)
    keys=[_fact_key(fact) for fact in facts]
    return dict(version=VERSION,source_sha256=hashlib.sha256(text.encode()).hexdigest(),
        role=role,terms=list(dict.fromkeys(terms))[:256],keys=list(dict.fromkeys(keys))[:32],
        operations=[k for k,p in OPS.items() if re.search(p,sample,re.I)],
        topics=[k for k,p in TOPICS.items() if re.search(p,sample,re.I)],
        times=list({(t["start"],t["end"]):t for t in expressions}.values())[:32],
        anchor_utc=utc_anchor(timestamp),template=hashlib.sha256(template.encode()).hexdigest(),
        authority="user_statement" if role=="user" else "assistant_statement_not_user_fact",
        facts=facts,events=[event for event,_ in retained],
        interpretation="heuristic_retrieval_hint_not_resolved_fact")


def _fact_key(fact):
    return fact["subject"]+":"+fact["attribute"]


def history_periods(features):
    """A mixed-topic message can belong to several source-scoped periods."""
    result=[]
    for event in features.get("events",[]):
        date=event["time_binding"].get("sort")
        for topic in event["topics"] or ["other"]:
            result.append(dict(topic=topic,period=date//100 if date is not None else 0,
                               event_span=[event["start"],event["end"]]))
    return result or [dict(topic="other",period=0,event_span=None)]


def _relevant_time(record, query_terms, scope_keys):
    facts=[f for f in record["features"].get("facts",[]) if _fact_key(f) in scope_keys]
    scores=[len(set(keyword_terms(f["subject"]))&query_terms) for f in facts]
    best=max(scores,default=0)
    if facts:
        relevant=[f for f,s in zip(facts,scores) if s==best] if best else facts
        # The message time fallback never becomes a resolved fact/event time.
        dates=[f.get("time_binding",{}).get("sort") for f in relevant
               if f.get("claim_kind")=="statement" or f.get("claim_kind")=="control_or_unresolved"]
        return max((d for d in dates if d is not None),default=None)
    events=[e for e in record["features"].get("events",[]) if set(e["terms"])&query_terms
            and e["claim_kind"]!="prospective"]
    dates={e["time_binding"]["sort"] for e in events if e["time_binding"]["sort"] is not None}
    return next(iter(dates)) if len(dates)==1 else None


def state_hints(records):
    groups=defaultdict(list)
    for r in records:
        if r["role"]!="user":
            continue
        for fact in r["features"].get("facts",[]):
            binding=fact.get("time_binding",{})
            effective=binding.get("sort") if fact.get("claim_kind")=="statement" else None
            groups[(fact["subject"],fact["attribute"])].append(dict(message_id=r["message_id"],
                value=fact["value"],span=[fact["start"],fact["end"]],effective=effective,
                time_binding=binding,claim_kind=fact.get("claim_kind","unknown"),
                source_sha256=r["features"]["source_sha256"]))
    hints=[]
    for (subject,attribute),items in groups.items():
        dated=[x for x in items if x["effective"] is not None]
        unresolved=[x for x in items if x["effective"] is None]
        newest=[x for x in dated if x["effective"]==max(y["effective"] for y in dated)] if dated else []
        status=("unresolved_same_time_conflict" if len({x["value"] for x in newest})>1 else
                "dated_candidates_with_unresolved_context" if newest and unresolved else
                "latest_explicit_time_candidates" if newest else "order_only_no_event_time_resolution")
        hints.append(dict(subject=subject,attribute=attribute,status=status,candidates=(newest+unresolved) if newest else items,
            historical_sources=[x["message_id"] for x in items],
            scope="Derived candidate hint only; withdrawals/restorations and clauses still require raw source interpretation"))
    return hints


def plan(records, query, seeds, limit=48, hops=2):
    """Reserve explicit update/control context, then bounded lexical graph closure."""
    q=set(keyword_terms(query)); by_id={r["message_id"]:r for r in records}
    df=Counter(t for r in records for t in r["features"]["terms"])
    term_sets={r["message_id"]:set(r["features"]["terms"]) for r in records}
    weights={t:math.log(1+len(records)/(n+1)) for t,n in df.items()}
    def overlap(r,terms):
        return sum(weights[t] for t in terms & term_sets[r["message_id"]])
    ranked=sorted(records,key=lambda r:(-overlap(r,q),r["session_id"],r["request_id"],r["ordinal"]))
    seed_ids=list(dict.fromkeys(s["message_id"] for row in seeds for s in row["sources"]))[:8]
    best=overlap(ranked[0],q) if ranked else 0
    matched=[r for r in ranked if overlap(r,q)>0 and overlap(r,q)>=best*.6][:8]
    initial=list(dict.fromkeys(seed_ids+[r["message_id"] for r in matched]))
    scope_keys={k for mid in initial if mid in by_id for k in by_id[mid]["features"]["keys"]}
    sessions={by_id[mid]["session_id"] for mid in seed_ids[:3] if mid in by_id}
    historical=bool(re.search(r"以前|当时|过去|截至|20\d{2}|historical|as of",query,re.I))
    current=not historical and bool(re.search(r"目前|现在|当前|现行|住|采用|使用|开放|负责人|current|latest",query,re.I))
    global_query=bool(re.search(r"总结|回顾|全局|全部经历|overview|summari[sz]e|whole history",query,re.I))
    controls=[r for r in ranked if r["role"]=="user" and
        (scope_keys & set(r["features"]["keys"]) or
         (r["session_id"] in sessions and set(r["features"]["operations"]) & {"update","withdraw","restore","conflict","privacy","rule"}))]
    def time_order(r):
        return (_relevant_time(r,q,scope_keys) or 0,r.get("timestamp") or 0,r["stored_at"],r["request_id"],r["ordinal"])
    if current:
        controls.sort(key=time_order,reverse=True)
    chosen=list(dict.fromkeys([r["message_id"] for r in controls[:12]]+initial))
    frontier=[by_id[mid] for mid in initial if mid in by_id]
    rounds=[]
    stop={"这个","那个","目前","现在","因此","因为","所以","使用","负责","方案","项目","规则","the","and"}
    for hop in range(hops):
        terms={t for r in frontier for t in r["features"]["terms"] if t not in q|stop and len(t)>=2
               and 1<df[t]<=max(3,len(records)*.2)}
        terms=set(sorted(terms,key=lambda t:(df[t],t))[:12])
        linked=sorted((r for r in records if r["message_id"] not in chosen and overlap(r,terms)>0),
            key=lambda r:(-overlap(r,terms),r["session_id"],r["request_id"],r["ordinal"]))[:8]
        rounds.append(dict(hop=hop+1,terms=sorted(terms),message_ids=[r["message_id"] for r in linked]))
        chosen.extend(r["message_id"] for r in linked); frontier=linked
        if not linked:
            break
    if re.search(r"规则|步骤|流程|例外|条件|推断|迁移|经验|rule|workflow|example",query,re.I):
        related=[r for r in ranked if set(r["features"]["operations"]) & {"rule","example","privacy"}
                 and (overlap(r,q)>0 or r["session_id"] in sessions)]
        chosen=list(dict.fromkeys([r["message_id"] for r in related[:12]]+chosen))
    if global_query:
        buckets=defaultdict(list)
        for r in records:
            if r["role"]!="user":
                continue
            for item in history_periods(r["features"]):
                key=(item["topic"],item["period"])
                if r not in buckets[key]:
                    buckets[key].append(r)
        diverse=[]; seen_templates=set()
        for depth in range(3):
            for key,items in sorted(buckets.items()):
                # All dates in this bucket were attached to its own source event.
                ordered=sorted(items,key=lambda r:(r.get("timestamp") or 0,r["stored_at"],r["request_id"],r["ordinal"]),reverse=True)
                distinct=[r for r in ordered if (key,r["features"]["template"]) not in seen_templates]
                if distinct:
                    r=distinct[0]; seen_templates.add((key,r["features"]["template"])); diverse.append(r["message_id"])
        chosen=list(dict.fromkeys(diverse+chosen))
    ids=chosen[:limit]
    return ids,dict(parser_version=VERSION,intents=dict(current=current,historical=historical,global_history=global_query),
        indexed_records=len(records),selected_parents=len(ids),controls=len(controls),link_rounds=rounds,
        state_hints=state_hints([by_id[mid] for mid in ids if mid in by_id]),
        temporal_selection=[dict(message_id=mid,scoped_event_time=_relevant_time(by_id[mid],q,scope_keys),
            history_periods=history_periods(by_id[mid]["features"])) for mid in ids if mid in by_id],
        limitation="Source-scoped date hints; uncertain/relative dates remain unknown. Message time/ingestion are ordering fallbacks only. No automatic fact conflict resolution or final answer.")
