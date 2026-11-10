"""Step 6a: evaluation harness - graph+hybrid agent vs plain vector-RAG baseline.
   python -m ti.evals [--system graph|baseline|both] [--only S1,F3] [--list]
Ground truth is computed independently from the raw JSON (not from Neo4j, not from any agent)."""
import asyncio, collections, json, os, re, sys, time
from .config import ROOT
from .parse import build_graph

# ---------------- oracle (independent ground truth) ----------------
def oracle():
    nodes, rels = build_graph(f"{ROOT}/data/calls")
    N = {(n["label"], n["id"]): n for n in nodes}
    acct_of, moments, mentions = collections.defaultdict(set), collections.defaultdict(list), collections.defaultdict(set)
    for r in rels:
        if r["type"] == "ABOUT": acct_of[r["from"][1]].add(r["to"][1])
        if r["type"] == "HAS_MOMENT": moments[r["from"][1]].append(N[tuple(r["to"])]["type"])
        if r["type"] == "MENTIONS" and r["to"][0] == "Competitor": mentions[r["to"][1]].add(r["from"][1])
    name = {d: N[("Account", d)]["name"] for d in [k[1] for k in N if k[0] == "Account"]}
    calls_by_acct = collections.defaultdict(list)
    for c, accts in acct_of.items():
        for a in accts: calls_by_acct[a].append(N[("Call", c)])
    for a in calls_by_acct: calls_by_acct[a].sort(key=lambda c: c["date"])
    churn = set()
    for a, cs in calls_by_acct.items():
        hit = [c for c in cs if "2026-03-10" <= c["date"] <= "2026-03-18" and "churn_signal" in moments[c["id"]]]
        if hit and not [c for c in cs if c["date"] > hit[-1]["date"]]: churn.add(name[a])
    comp = {k: {name[a] for c in v for a in acct_of.get(c, ())} for k, v in mentions.items()}
    repeat = {name[a] for a, cs in calls_by_acct.items() if sum(c["type"] == "support" for c in cs) >= 2}
    delta = {name[a]: cs[-1]["sentiment_score"] - cs[0]["sentiment_score"] for a, cs in calls_by_acct.items() if len(cs) >= 2}
    best = max(delta, key=lambda k: delta[k])
    return dict(all=set(name.values()), churn=churn, comp=comp, repeat=repeat, recovery=best, recovery_delta=round(delta[best], 1))

# ---------------- scoring ----------------
NUMW = {12: "twelve", 6: "six", 3: "three", 8: "eight"}
def mentioned(ans, names): return {n for n in names if n.lower() in ans.lower()}

def score_set(ans, expected, universe):
    got = mentioned(ans, universe); hit = got & expected
    p = len(hit) / len(got) if got else 0.0; r = len(hit) / len(expected)
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return dict(passed=f1 >= 0.8, score=round(f1, 2), detail=f"recall {len(hit)}/{len(expected)}, precision {p:.2f}, extra={sorted(got - expected)}")

def score_count(ans, n):
    ok = bool(re.search(rf"\b{n}\b|\b{NUMW.get(n, '#')}\b", ans, re.I))
    return dict(passed=ok, score=1.0 if ok else 0.0, detail=f"expects {n}")

def score_facts(ans, pats):
    hit = [bool(re.search(p, ans, re.I)) for p in pats]
    return dict(passed=all(hit), score=round(sum(hit) / len(hit), 2), detail=f"{sum(hit)}/{len(pats)} facts")

def score_no_hallucination(ans):
    admits = bool(re.search(r"no (information|data|mention|record|details?|ARR|contract|revenue)|not (available|in|included|provided|contained|found|mentioned|specified|disclosed)|do(es)? not (mention|contain|include|specify|provide)|unavailable|cannot|can't|isn't|doesn't|does not", ans, re.I))
    invented = bool(re.search(r"\$\s?\d", ans))
    return dict(passed=admits and not invented, score=1.0 if admits and not invented else 0.0, detail=f"admits_gap={admits}, invented_$={invented}")

def score_rules(ans, must, forbid):
    """must: every pattern has to appear. forbid: none may appear. Use for failure modes found in real answers."""
    miss = [p for p in must if not re.search(p, ans, re.I)]
    bad = [p for p in forbid if re.search(p, ans, re.I)]
    n = len(must) + len(forbid)
    return dict(passed=not miss and not bad, score=round(1 - (len(miss) + len(bad)) / n, 2) if n else 1.0,
                detail=f"missing={len(miss)}, forbidden_hit={len(bad)}" + (f" {bad[0][:40]}" if bad else ""))

def questions(O):
    S = lambda i, q, key, label: dict(id=i, q=q, kind="set", exp=O["comp"][key], label=label)
    return [
     dict(id="S1", q="Which customers raised churn signals during the March outage and haven't had a call since?", kind="set", exp=O["churn"], label="graph: churn + absence of later call"),
     S("S2", "Which customer accounts mention SentinelShield in their calls?", "SentinelShield", "graph: competitor -> accounts"),
     S("S3", "Which customer accounts mention VaultEdge in their calls?", "VaultEdge", "graph: competitor -> accounts"),
     S("S4", "Which customer accounts mention CyberNova in their calls?", "CyberNova", "graph: competitor -> accounts"),
     dict(id="S5", q="Which accounts have opened two or more support cases?", kind="set", exp=O["repeat"], label="graph: aggregation"),
     dict(id="C1", q="How many customer accounts mention SentinelShield in their calls? Give the number.", kind="count", exp=len(O["comp"]["SentinelShield"]), label="graph: counting"),
     dict(id="T1", q="Among customers with at least two calls, which account's sentiment score improved the most from its first call to its last call?", kind="facts", exp=[re.escape(O["recovery"])], label=f"graph: temporal ({O['recovery']}, +{O['recovery_delta']})"),
     dict(id="F1", q="Trailhead Marketplace looked like a churn risk in March. What changed by April?", kind="facts", exp=[r"circuit breaker|redundan", r"renew"], label="evidence"),
     dict(id="F2", q="Give me a brief on Northstar Pharma's account health.", kind="facts", exp=[r"SentinelShield", r"CISO", r"June"], label="evidence"),
     dict(id="F3", q="What was the root cause of the March Detect outage and what was the fix?", kind="facts", exp=[r"single point of failure", r"circuit breaker", r"redundan"], label="evidence (internal)"),
     dict(id="F4", q="When did Comply v2 launch?", kind="facts", exp=[r"April 7|7 April|2026-04-07|Apr 7"], label="evidence"),
     dict(id="F5", q="How long did customers lose threat monitoring visibility during the March outage?", kind="facts", exp=[r"\bsix\b|\b6[- ]hours?", r"\b(?:[7-9]|[1-9][0-9]|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty)\+?(?:\s*(?:-|–|to|or)\s*(?:[0-9]+|\w+))?\s*(?:[- ])?(?:hours?|hrs?)\b|over a day|a full day|more than a day"], label="conflict surfacing (official 6h vs customer-reported longer)"),
     dict(id="N1", q="What is Northstar Pharma's annual contract value (ARR)?", kind="neg", exp=None, label="hallucination control (ARR is not in the data)"),
     dict(id="F6", q="What did engineering say internally about the outage that customers were never told?", kind="rules", exp=None,
          must=[r"cascad", r"Cobalt|Trailhead|Ridgeline|told (the )?customers?|support (staff|team)? ?(told|explained)"],
          forbid=[r"never (been )?(told|disclosed|shared)", r"(were|was) not (explicitly )?(shared|told|disclosed)", r"not (explicitly )?(shared|communicated) (with|to) customers"],
          label="false premise: support DID tell customers about the cascading failure (03-10 Cobalt, 03-11 Trailhead)"),
     dict(id="F7", q="When did the March Detect outage begin?", kind="rules", exp=None,
          must=[r"March 10|10 March|2026-03-10"],
          forbid=[r"(began|started|first (occurred|began)|start(ed)? on|starting)[^.\n]{0,40}(March|Mar) 15"],
          label="incident start: Mar 10 (a further Mar 15 disruption is allowed, calling Mar 15 the START is not)"),
     dict(id="F8", q="How is Comply v2 landing with customers since launch?", kind="rules", exp=None,
          must=[r"April 7|7 April|2026-04-07"],
          forbid=[r"Launch Day Checklist|Comply v2 Preview|GA Deployment Plan|Launch Readiness|Early Access"],
          label="time window: only calls on/after the 2026-04-07 GA date"),
     dict(id="F9", q="Was the Detect reliability fix delivered on the date engineering originally committed to?", kind="rules", exp=None,
          must=[r"end of March|March 31|late March", r"April 8|8 April|2026-04-08", r"late|slip|delay|missed|behind|buffer|week"],
          forbid=[], label="commitment vs delivery (target end of March; April 8 build)"),
     dict(id="F10", q="How many support calls mentioned the outage?", kind="rules", exp=None,
          must=[r"coverage|partial|incomplete|truncat|excerpt|not the full|portion of"],
          forbid=[], label="discloses partial transcript coverage (median ~29%)"),
    ]

def grade(q, ans, O):
    return {"set": lambda: score_set(ans, q["exp"], O["all"]), "count": lambda: score_count(ans, q["exp"]),
            "facts": lambda: score_facts(ans, q["exp"]), "neg": lambda: score_no_hallucination(ans),
            "rules": lambda: score_rules(ans, q["must"], q["forbid"])}[q["kind"]]()

# ---------------- run ----------------
NEUTRAL = """You are a transcript analyst for Aegis Cloud Security (B2B SaaS security; products Detect, Comply, Protect, Identity,
Backup/Recover). You answer questions for sales, support, product and engineering leaders using call transcripts."""

# Both systems get identical instructions and rules; they differ ONLY in tools (agent_base.COMMON_RULES vs BASELINE_RULES differ in one tool-usage line).

def _make(make_agent, name, instructions, rules, tools):
    """Build an agent whether make_agent takes (name, instructions, tools) or also a `rules` argument."""
    import inspect
    params = inspect.signature(make_agent).parameters
    if "rules" in params:
        return make_agent(name, instructions, tools, rules=rules)
    try:
        if "COMMON_RULES" in inspect.getsource(make_agent) and rules is not COMMON_RULES_REF[0]:
            print(f"WARNING: make_agent appends COMMON_RULES itself, so '{name}' also receives the graph-tool rules. "
                  "The baseline comparison is contaminated until make_agent accepts a `rules` argument.")
    except (OSError, TypeError):
        pass
    return make_agent(name, instructions + "\n\n" + rules, tools)

COMMON_RULES_REF: list[str | None] = [None]   # set in run() so _make can tell graph rules from baseline rules

async def run(systems, only):
    import importlib
    from .agent_base import make_agent, ask, COMMON_RULES, BASELINE_RULES
    from .agent_tools import ALL_TOOLS, TRACE
    # BASELINE_TOOLS may not exist in agent_tools.py; derive "search_transcripts only" if it does not.
    BASELINE_TOOLS = getattr(importlib.import_module(".agent_tools", __package__), "BASELINE_TOOLS", None) \
        or [t for t in ALL_TOOLS if "search_transcripts" in str(getattr(t, "name", None) or getattr(t, "__name__", None) or t)]
    COMMON_RULES_REF[0] = COMMON_RULES
    assert BASELINE_TOOLS, "could not find a search_transcripts-only tool list for the baseline"
    O = oracle(); qs = [q for q in questions(O) if not only or q["id"] in only]
    # Preflight: refuse to run (and score) an evaluation whose search tools are broken.
    from . import tools as _T
    for label, fn in (("hybrid search_transcripts", lambda: _T.search_transcripts("outage", k=1)), ("vector_search", lambda: _T.vector_search("outage", k=1))):
        try: fn()
        except Exception as e:
            sys.exit(f"PREFLIGHT FAILED: {label} -> {type(e).__name__}: {e}\nFix this first (run: python -m ti.diagnose). Scoring a run with broken search would be meaningless.")
    agents = {"graph": _make(make_agent, "EvalGraph", NEUTRAL, COMMON_RULES, ALL_TOOLS),
              "baseline": _make(make_agent, "EvalBaseline", NEUTRAL, BASELINE_RULES, BASELINE_TOOLS)}
    results = []
    for q in qs:
        for s in systems:
            TRACE.clear(); t0 = time.time(); err = None
            try: ans = await ask(agents[s], q["q"], session=agents[s].create_session())
            except Exception as e: ans, err = "", f"{type(e).__name__}: {e}"
            g = grade(q, ans, O) if not err else dict(passed=False, score=0.0, detail=err)
            n_err = sum("ERROR" in t for t, _ in TRACE)
            if n_err: g = dict(passed=False, score=0.0, detail=f"INVALID: {n_err} tool error(s) - not scored")
            results.append(dict(id=q["id"], system=s, label=q["label"], question=q["q"], answer=ans, tool_errors=n_err, tools=[t for t, _ in TRACE],
                                seconds=round(time.time() - t0, 1), **g))
            print(f"{q['id']:>3} {s:<8} {'INVALID' if n_err else ('PASS' if g['passed'] else 'FAIL')}  {g['score']:.2f}  {g['detail']}", flush=True)
    return results

def report(results):
    os.makedirs(f"{ROOT}/out", exist_ok=True)
    json.dump(results, open(f"{ROOT}/out/eval_results.json", "w", encoding="utf-8"), indent=2, default=str, ensure_ascii=False)
    systems = sorted({r["system"] for r in results}); ids = list(dict.fromkeys(r["id"] for r in results))
    L = ["| Q | Type | " + " | ".join(systems) + " |", "|---|---|" + "---|" * len(systems)]
    for i in ids:
        row = [r for r in results if r["id"] == i]
        L.append(f"| {i} | {row[0]['label']} | " + " | ".join(
            next((("INVALID" if r.get("tool_errors") else ("PASS" if r["passed"] else "FAIL") + f" ({r['score']:.2f})") for r in row if r["system"] == s), "-") for s in systems) + " |")
    L += ["", "| System | Passed | Mean score | Avg seconds | Avg tool calls |", "|---|---|---|---|---|"]
    for s in systems:
        allr = [r for r in results if r["system"] == s]; rs = [r for r in allr if not r.get("tool_errors")]
        n = len(rs) or 1
        L.append(f"| {s} | {sum(r['passed'] for r in rs)}/{len(rs)} valid ({len(allr) - len(rs)} invalid) | {sum(r['score'] for r in rs)/n:.2f} | "
                 f"{sum(r['seconds'] for r in rs)/n:.0f} | {sum(len(r['tools']) for r in rs)/n:.1f} |")
    open(f"{ROOT}/out/eval_results.md", "w", encoding="utf-8").write("\n".join(L)); print("\n" + "\n".join(L))
    print(f"\nFull answers: out/eval_results.json   |   table: out/eval_results.md")

if __name__ == "__main__":
    a = sys.argv[1:]
    if "--list" in a:
        O = oracle()
        for q in questions(O): print(q["id"], "|", q["label"], "|", q["q"], "|", q["exp"] if q["kind"] != "set" else sorted(q["exp"]))
        sys.exit()
    if "--rescore" in a:
        O = oracle(); Q = {q["id"]: q for q in questions(O)}
        res = json.load(open(f"{ROOT}/out/eval_results.json", encoding="utf-8"))
        for r in res:
            if r["id"] in Q and r.get("answer"): r.update(grade(Q[r["id"]], r["answer"], O))
        report(res); sys.exit()
    sysarg = a[a.index("--system") + 1] if "--system" in a else "both"
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    if sys.platform == "win32": asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    report(asyncio.run(run(["graph", "baseline"] if sysarg == "both" else [sysarg], only)))