"""Step 1: turn the raw call JSON into a graph (nodes + relationships). Deterministic, no LLM."""
import csv, json, os, re
from datetime import datetime

INTERNAL_DOMAIN = "aegiscloud.com"
PRODUCTS = {"Detect": r"\bdetect\b", "Comply": r"\bcomply\b", "Protect": r"\bprotect\b",
            "Identity": r"\bidentity\b", "Backup": r"\b(backup|recover(y)?)\b",
            "LogVault": r"logvault", "CloudPrime": r"cloudprime"}
COMPETITORS = ["SentinelShield", "VaultEdge", "CyberNova", "Fortiguard", "Clearvale"]
OUTAGE_RE = re.compile(r"\boutage\b|pipeline failure|ingestion layer", re.I)
OUTAGE_START = "2026-03-10"  # first war-room call
INCIDENT_ID = "detect-outage-2026-03"
CHUNK_TURNS, CHUNK_OVERLAP = 6, 1


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _slug(name):
    return re.sub(r"[^a-z.]", "", name.lower().replace(" ", "."))


def _account_names(calls):
    """domain -> display name, taken from titles like 'Aegis / Name - ...' (fallback: domain stem)."""
    names = {}
    for c in calls:
        m = re.match(r"^(?:Aegis / |URGENT: |ESCALATION: )(.+?) - ", c["info"]["title"])
        if m:
            for d in c["ext"]:
                names.setdefault(d, m.group(1))
    return names


def read_calls(root):
    calls = []
    for cid in sorted(os.listdir(root)):
        p = os.path.join(root, cid)
        if not os.path.isdir(p):
            continue
        info = _load(f"{p}/meeting-info.json")
        calls.append(dict(
            id=cid, info=info, summ=_load(f"{p}/summary.json"),
            turns=_load(f"{p}/transcript.json")["data"],
            ext={e.split("@")[-1] for e in info["allEmails"]} - {INTERNAL_DOMAIN}))
    return calls


def call_type(c):
    if c["info"]["title"].startswith("Support Case"):
        return "support"
    return "external" if c["ext"] else "internal"


def build_graph(root, people_csv=None, accounts_csv=None):
    calls = read_calls(root)
    acct_names = _account_names(calls)
    nodes, rels = {}, []

    def node(label, nid, **props):
        nodes.setdefault((label, nid), {"label": label, "id": nid}).update(props)

    def rel(a, typ, b, **props):
        rels.append({"from": a, "type": typ, "to": b, "props": props})

    roles = {}
    if people_csv and os.path.exists(people_csv):
        roles = {r["email"]: r for r in csv.DictReader(open(people_csv, encoding="utf-8"))}
    acct_extra = {}
    if accounts_csv and os.path.exists(accounts_csv):
        acct_extra = {r["domain"]: r for r in csv.DictReader(open(accounts_csv, encoding="utf-8"))}

    for p in PRODUCTS: node("Product", p, name=p)
    for c in COMPETITORS: node("Competitor", c, name=c)
    node("Incident", INCIDENT_ID, name="Detect event-pipeline outage", start="2026-03-10")

    for c in calls:
        i, s, cid = c["info"], c["summ"], c["id"]
        text = " ".join(t["sentence"] for t in c["turns"])
        full = f'{i["title"]} {s["summary"]} {text}'
        node("Call", cid, title=i["title"], date=i["startTime"][:10], start=i["startTime"],
             duration_min=i["duration"], coverage=round(max(t["endTime"] for t in c["turns"]) / (i["duration"] * 60), 2), type=call_type(c), summary=s["summary"],
             sentiment=s["overallSentiment"], sentiment_score=s["sentimentScore"],
             topics=s["topics"])
        # people
        name_by_slug = {_slug(t["speaker_name"]): t["speaker_name"] for t in c["turns"]}
        for email in i["allEmails"]:
            internal = email.endswith("@" + INTERNAL_DOMAIN)
            slug = email.split("@")[0]
            r = roles.get(email, {})
            node("Person", email, name=name_by_slug.get(slug, slug), internal=internal,
                 role=r.get("role"), team=r.get("team"))
            rel(("Person", email), "ATTENDED", ("Call", cid))
        # accounts
        for d in c["ext"]:
            x = acct_extra.get(d, {})
            node("Account", d, name=acct_names.get(d, d.split(".")[0].title()),
                 arr=float(x["arr_usd"]) if x.get("arr_usd") else None,
                 renewal_date=x.get("renewal_date") or None, tier=x.get("tier") or None)
            rel(("Call", cid), "ABOUT", ("Account", d))
        # products / competitors / incident (vocabulary match; Step 2 can add LLM linking)
        for p, pat in PRODUCTS.items():
            if re.search(pat, full, re.I): rel(("Call", cid), "MENTIONS", ("Product", p))
        for k in COMPETITORS:
            if re.search(k, text, re.I): rel(("Call", cid), "MENTIONS", ("Competitor", k))
        if OUTAGE_RE.search(full) and i["startTime"][:10] >= OUTAGE_START:
            rel(("Call", cid), "RELATES_TO", ("Incident", INCIDENT_ID))
        # topics
        for t in s["topics"]:
            node("Topic", t.lower(), name=t.lower()); rel(("Call", cid), "HAS_TOPIC", ("Topic", t.lower()))
        # moments
        for n, k in enumerate(s["keyMoments"]):
            mid = f"{cid}:m{n}"
            node("Moment", mid, type=k["type"], text=k["text"], time=k["time"], speaker=k.get("speaker"))
            rel(("Call", cid), "HAS_MOMENT", ("Moment", mid))
        # action items ("Owner: text")
        for n, a in enumerate(s["actionItems"]):
            aid = f"{cid}:a{n}"
            owner, _, body = a.partition(": ")
            node("ActionItem", aid, text=body or a, owner_name=owner if body else None)
            rel(("Call", cid), "HAS_ACTION", ("ActionItem", aid))
            for (lab, pid), pn in list(nodes.items()):
                if lab == "Person" and pn.get("name") == owner and pn.get("internal"):
                    rel(("Person", pid), "OWNS", ("ActionItem", aid)); break
        # chunks (for vector search in Step 3; embeddings added later)
        step = CHUNK_TURNS - CHUNK_OVERLAP
        for n, a in enumerate(range(0, len(c["turns"]), step)):
            win = c["turns"][a:a + CHUNK_TURNS]
            if not win: break
            chid = f"{cid}:c{n}"
            node("Chunk", chid, text="\n".join(f'{t["speaker_name"]}: {t["sentence"]}' for t in win),
                 start=win[0]["time"], end=win[-1]["endTime"], first_turn=win[0]["index"], last_turn=win[-1]["index"])
            rel(("Chunk", chid), "PART_OF", ("Call", cid))
            if a + CHUNK_TURNS >= len(c["turns"]): break
    return list(nodes.values()), rels
