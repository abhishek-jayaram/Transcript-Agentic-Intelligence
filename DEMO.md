# Demo script (about 12 minutes)

Goal: show that a **graph + hybrid-search agent** answers questions a plain vector-search agent cannot, that it **cites its evidence**,
that it **admits what the data cannot tell it**, and that you can **watch it work** (tool trace in the UI, traces in Azure).

## Before you start (5 minutes, once)
1. `az login`, then `cd src ; python -m ti.web` and open http://127.0.0.1:8000. The console should say `Telemetry: ON ...`.
2. Ask each demo question once as a rehearsal. Answers take a while (watch the "Working... Ns" timer), and the model can word things differently each time.
3. Optional but strong: produce the side-by-side table for the four "graph wins" questions (it overwrites `out\eval_results.json`, so copy that file first if you want to keep it):
   ```
   copy ..\out\eval_results.json ..\out\eval_results.full.json
   python -m ti.evals --only S1,S5,C1,T1 --system both
   ```
   Then open `out\eval_results.md`.
4. Open Application Insights in a second tab (Investigate > Transaction search), time range "last 30 minutes".

Data to keep in mind: 100 calls (43 external, 30 internal, 27 support), 2026-02-03 to 2026-04-28, 32 customer accounts.
Transcripts are excerpts (median about 29% of each call), so every count is a lower bound. The agent says so, and you should too.

## Part 1 - Graph questions (the agent counts and follows relationships)

### 1. Churn risk with no follow-up  (persona: Sales Manager)
Ask: **Which customers raised churn signals during the March outage and haven't had a call since? What should we do about each?**
- Expected accounts: **Helix Data, Northstar Pharma, Ridgeline Logistics** (this list is computed independently from the raw data).
- Open "how I answered": it should show `graph_query churn_no_followup`, then searches for evidence quotes.
- Say: "'No call since' is a relationship in the graph. A vector search finds passages that sound like churn, but cannot tell you who went quiet afterwards."

### 2. Counting  (persona: Sales Manager)
Ask: **How many customer accounts mention SentinelShield in their calls?**
- Expected: **12** accounts, followed by the note that transcripts are excerpts so the count is a lower bound.
- Trace: `graph_query competitor_mentions`.
- Say: "Counting by retrieving the top 6 passages is guesswork. Here the database counts, and the agent still tells you the number is a floor."

### 3. Biggest turnaround  (persona: Copilot auto)
Ask: **Among customers with at least two calls, which account's sentiment improved the most from its first call to its last?**
- Expected: **Trailhead Marketplace** (score 1.4 on the 2026-03-11 support case to 4.5 on the 2026-04-05 renewal confirmation, +3.1).
- Trace: `graph_query sentiment_change`. The orchestrator also names which persona lens it used.

## Part 2 - Evidence and judgement (the agent cites and checks the question)

### 4. Root cause  (persona: Engineering Lead)
Ask: **Walk me through the March Detect outage: root cause, what we committed to fix, and whether it was delivered.**
- Expected themes: a **single point of failure**, a **circuit breaker** and **redundancy** as the fix. Each claim is cited as (call title, date).

### 5. Committed date vs actual date  (persona: Engineering Lead)
Ask: **Was the Detect reliability fix delivered on the date engineering originally committed to?**
- Expected: committed for **end of March**, actual build **April 8** (pipeline 4.1.2, confirmed in the 2026-04-22 Stratos Cloud call), so about a week late. Both calls are named.
- Say: "It has to find two facts in two different calls and compare them."

### 6. Time window  (persona: Product Manager)
Ask: **How is Comply v2 landing with customers since launch?**
- Expected: only calls **on or after 2026-04-07** (the GA date). It should not cite pre-launch calls such as the launch checklist or the early-access calls.

### 7. Not in the data  (any persona)
Ask: **What is Northstar Pharma's annual contract value (ARR)?**
- Expected: it says contract value is **not in the transcripts** and does not invent a number.
- Say: "The most important thing for a business user to trust: it says 'I don't know'."

## Part 3 - Watching it work

### 8. The trace in the UI
Click "how I answered" under any answer: each line is a tool call (`graph_query` template or search with its filters). The same trace is what the evals read.

### 9. The trace in Azure
In Application Insights (Transaction search) open the most recent `ti.question`. Point at the child spans: `ti.graph_query`, `ti.search_transcripts` and its embed / vector / keyword steps, plus the model calls. In Logs:
```
dependencies | where name startswith "ti." | summarize calls=count(), avg_ms=avg(duration) by name | order by avg_ms desc
```
Say: "Prompts and answers are not sent to Azure (ENABLE_SENSITIVE_DATA is false); we only see timings, counts and tool names."

### 10. The scoreboard
Show `out\eval_results.md`. Honest numbers: in the last graph-only run the agent passed 14 of 18 checks (mean score 0.89). In the earlier side-by-side run the graph agent passed 13 of 18 (mean 0.89) and the vector-only baseline passed 4 of 18 (mean 0.45). Results vary a little between runs because the model is not deterministic.

## Questions to avoid, or to show as honest limits
These four evals still fail, so they can go wrong live:

| Question | What can happen |
|---|---|
| "Give me a one-page brief on account health for Northstar Pharma." | May omit the **June** renewal, the CISO escalation or SentinelShield. |
| "Trailhead Marketplace looked like a churn risk in March. What changed by April?" | May miss the circuit-breaker fix or the renewal. |
| "How long did customers lose threat monitoring visibility during the March outage?" | May give only the official **six hours** and miss the longer customer-reported figures (about 9-10 hours). |
| "What did engineering say internally about the outage that customers were never told?" | The question assumes customers were never told. Support **did** tell Cobalt (2026-03-10) and Trailhead (2026-03-11) about the cascading failure. The agent should say so, but sometimes still echoes the wording. |

If you do want to show one, present it as the known limit, and say what the fix would be (more targeted graph templates and a stricter answer check).

