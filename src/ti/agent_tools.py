"""Agent-facing wrappers around ti.tools (Step 3). Returns compact JSON strings and records every call in TRACE."""
import json, re, sys, traceback
from typing import Annotated
from agent_framework import tool
from . import tools as T

TRACE = []   # (tool, args) for each call; the CLI prints it with --trace, the eval harness reads it later
MAX_CHARS = 12000

def _fail(tool_name, exc):
    """Make tool failures visible: print the real error, record it, and tell the model to disclose it."""
    detail = f"{type(exc).__name__}: {exc}"
    for attr in ("status_code", "body"):
        if getattr(exc, attr, None) is not None:
            detail += f" | {attr}={getattr(exc, attr)}"
    print(f"  [tool ERROR] {tool_name}: {detail}", file=sys.stderr)
    TRACE.append((tool_name + " ERROR", {"error": detail}))
    return json.dumps({"error": f"{tool_name} failed - {detail}",
                       "instruction": "Evidence from this tool is UNAVAILABLE. Say so explicitly in your answer and keep conclusions tentative."})

def _pack(rows):
    s = json.dumps(rows, default=str, ensure_ascii=False)
    if len(s) > MAX_CHARS:
        keep = rows[: max(1, int(len(rows) * MAX_CHARS / len(s)))]
        return json.dumps({"truncated": True, "shown": len(keep), "total": len(rows), "rows": keep}, default=str, ensure_ascii=False)
    return s

_TEMPLATE_HELP = "\n".join(f"- {n}: {d} Params: {json.dumps(defs)}" for n, (d, defs, _) in T.TEMPLATES.items())

@tool(name="graph_query", description=(
    "Run a vetted query on the transcript knowledge graph. Best for lists, counts, rankings, timelines and "
    "'who has/hasn't...' questions. Rows include call_id(s) for citation. Templates:\n" + _TEMPLATE_HELP))
def graph_query(template: Annotated[str, "Template name, e.g. churn_no_followup"],
                params_json: Annotated[str, "JSON object of template params (omit keys to use defaults), e.g. {\"competitor\": \"SentinelShield\"}"] = "") -> str:
    try:
        params = json.loads(params_json) if params_json.strip() else {}
    except json.JSONDecodeError:
        return json.dumps({"error": "params_json must be a JSON object"})
    TRACE.append(("graph_query", {"template": template, **params}))
    try:
        res = T.graph_query(template, params)
        if isinstance(res, dict) and "error" in res:  # unknown template / bad params come back as a dict, not an exception
            return _fail("graph_query", RuntimeError(f"{res['error']} (available: {res.get('available', [])})"))
        return _pack(res)
    except Exception as e:
        return _fail("graph_query", e)

@tool(name="search_transcripts", description=(
    "Hybrid semantic + keyword search over call transcript passages. Use to get evidence and verbatim quotes, "
    "or for open-ended 'what did customers say about X' questions. Every hit has a citation."))
def search_transcripts(query: Annotated[str, "Natural-language search query"],
                       k: Annotated[int, "Number of passages (default 6, max 10)"] = 6,
                       account: Annotated[str | None, "Optional account name substring, e.g. Northstar"] = None,
                       call_type: Annotated[str | None, "Optional: support, external (account-management) or internal"] = None,
                       date_from: Annotated[str | None, "Optional YYYY-MM-DD"] = None,
                       date_to: Annotated[str | None, "Optional YYYY-MM-DD"] = None) -> str:
    TRACE.append(("search_transcripts", {"query": query, "account": account, "call_type": call_type, "date_from": date_from, "date_to": date_to}))
    try:
        hits = T.search_transcripts(query, k=min(max(k, 1), 10), account=account, call_type=call_type, date_from=date_from, date_to=date_to)
    except Exception as e:
        return _fail("search_transcripts", e)
    slim = [{"citation": h["citation"], "call_id": h["call_id"], "account": h["account"], "call_type": h["call_type"], "text": h["text"][:900]} for h in hits]
    out = _pack(slim)
    asked_duration = re.search(r"hours?|duration|how long|lasted|down for|visibility", query, re.I)
    called = any(t == "graph_query" and a.get("template") == "customer_outage_durations" for t, a in TRACE)
    if asked_duration and not called:  # nudge: free-text search anchors on the official figure
        out = json.dumps({"STOP_DO_NOT_ANSWER_YET": "You searched for duration but have NOT called graph_query('customer_outage_durations'). "
                          "Per rule 4 this call is MANDATORY before answering any duration/how-long question. "
                          "Call graph_query with template='customer_outage_durations' NOW, then present every customer-reported figure "
                          "alongside the official figure.", "results": json.loads(out)}, ensure_ascii=False)
    return out

ALL_TOOLS = [graph_query, search_transcripts]

@tool(name="search_transcripts", description="Semantic (vector) search over call transcript passages. Returns passages with citations.")
def vector_only_search(query: Annotated[str, "Natural-language search query"],
                       k: Annotated[int, "Number of passages (default 6, max 10)"] = 6) -> str:
    TRACE.append(("vector_search", {"query": query}))
    try:
        hits = T.vector_search(query, k=min(max(k, 1), 10))
    except Exception as e:
        return _fail("vector_search", e)
    return _pack([{"citation": h["citation"], "call_id": h["call_id"], "account": h["account"], "call_type": h["call_type"], "text": h["text"][:900]} for h in hits])

BASELINE_TOOLS = [vector_only_search]
