"""python -m ti.verify_tools  - checks each Cypher template against answers computed independently from the graph file."""
from typing import Any
from . import tools
from .tools import search_transcripts

def graph_query(template: str, params: dict | None = None) -> list[dict[str, Any]]:
    r = tools.graph_query(template, params)
    assert isinstance(r, list), f"graph_query returned an error: {r}"
    return r
ok = True
def check(name: str, cond: Any, detail: Any = "") -> None:
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail)

r = graph_query("churn_no_followup")
check("churn_no_followup", sorted(x["account"] for x in r) == ["Helix Data", "Northstar Pharma", "Ridgeline Logistics"], [x["account"] for x in r])
for k, n in [("SentinelShield", 12), ("VaultEdge", 6), ("CyberNova", 3)]:
    r = graph_query("competitor_mentions", {"competitor": k}); check(f"competitor {k} accounts", len(r) == n, len(r))
r = graph_query("repeat_support_accounts"); check("repeat_support (>=2) accounts", len(r) == 8 and r[0]["account"] == "Silverline Brands", [x["account"] for x in r][:3])
r = graph_query("incident_impact"); check("incident_impact accounts", len(r) == 24, len(r))
r = graph_query("commitments_after_incident", {"limit": 500}); check("incident action items", len(r) == 207, len(r))
r = graph_query("top_topics"); check("top_topics", r[0]["topic"] == "compliance" and r[0]["calls"] == 23, r[0])
r = graph_query("account_timeline", {"account": "Trailhead"}); check("account_timeline Trailhead", len(r) == 2 and r[0]["score"] == 1.4 and r[1]["score"] == 4.5, [(x["date"], x["score"]) for x in r])
r = graph_query("moments_by_type", {"type": "feature_gap", "limit": 500}); check("feature_gap moments", len(r) == 51, len(r))
r = graph_query("sentiment_change"); check("sentiment_change top = Trailhead +3.1", r[0]["account"] == "Trailhead Marketplace" and r[0]["change"] == 3.1, (r[0]["account"], r[0]["change"]))
r = graph_query("incident_calls_by_type"); got = {x["call_type"]: x["calls"] for x in r}
check("incident_calls_by_type", got == {"internal": 21, "external": 21, "support": 10}, got)
r = graph_query("incident_timeline"); check("incident_timeline starts 2026-03-10", r[0]["date"] == "2026-03-10", [(x["date"], x["call_type"]) for x in r[:2]])
r = graph_query("moments_by_type", {"type": "praise", "product": "Comply v2", "since": "2026-04-07", "limit": 500}); check("praise Comply v2 since GA: none before 04-07", len(r) > 0 and all(x["date"] >= "2026-04-07" for x in r), len(r))
r = graph_query("account_brief", {"account": "Northstar"}); check("account_brief Northstar has competitor + CISO/renewal signals", len(r) == 1 and "SentinelShield" in r[0]["competitors"] and any(("CISO" in e or "renew" in e.lower()) for e in r[0]["signal_excerpts"]), r[0]["competitors"] if r else r)
r = graph_query("customer_outage_durations"); check("customer_outage_durations returns customer excerpts", len(r) > 0 and all(x["call_type"] in ("external", "support") for x in r), len(r))
print("\nHYBRID SEARCH: 'customer threatening to leave after the outage'")
for h in search_transcripts("customer threatening to leave after the outage", k=5):
    print(f'  rrf={h["rrf"]} v={h["in_vector"]} kw={h["in_keyword"]}  {h["citation"]}')
print("\nALL TEMPLATE CHECKS PASSED" if ok else "\nSOME CHECKS FAILED - send me the output")
