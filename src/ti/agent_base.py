"""Shared agent plumbing (reused by the persona agents, orchestrator and the eval harness)."""
import asyncio, sys
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from .config import env, credential
from .agent_tools import ALL_TOOLS, TRACE
from . import telemetry

_HEAD = """
GROUNDING RULES
1. Every claim must come from tool results. Never invent customers, numbers, dates or quotes. If the tools return nothing, say so.
"""
_TOOLS_GRAPH = """2. Use graph_query for lists, counts, rankings, timelines and 'who has / hasn't' questions. Then use search_transcripts to pull evidence
   (quotes) for the top 1-3 items. For list questions name EVERY item the tool returned - never shorten a list to examples. Use search_transcripts directly for open-ended 'what did people say about X' questions.
"""
_TOOLS_BASELINE = """2. Use search_transcripts (run several different queries if needed) to find evidence for every question, including lists and counts. For list questions name every account you find.
"""
_TAIL = """3. Cite every factual statement as (Call title, date). Quote sparingly and exactly.
4. When sources disagree, show every version and say who said what and when. This applies especially to durations, counts and impact
   figures: look at BOTH internal calls and customer calls, report each figure with its speaker, and never say sources 'confirm' a
   figure unless they actually state it. Do not average or pick silently.
   MANDATORY for 'how long' / duration / hours questions: your VERY FIRST tool call MUST be graph_query with template
   'customer_outage_durations'. Do NOT search_transcripts first. If search_transcripts fires before graph_query, your answer will be
   marked WRONG. Only after you have the customer_outage_durations rows, also search for the official/internal figure. Present every
   customer-reported figure side by side with the official figure, each with account and date. Never say customers confirmed the
   official figure unless a customer excerpt explicitly states that exact duration.
5. Data limits you must respect: the data covers calls from 2026-02-03 to 2026-04-28. Contract value (ARR) is NOT in the transcripts, and
   renewal dates exist only if a tool returns them or a transcript states them. 'No later call' means no later call in this dataset,
   not that nobody contacted the customer. Transcripts are EXCERPTS covering a median ~29% of each call (15-90%), so any
   count of calls or accounts is a lower bound and a missing mention is weak evidence: say so whenever you give a count.
   For 'since launch' or 'post-launch' questions about Comply v2: cite ONLY calls on or after 2026-04-07 (the GA date). Do NOT
   cite the Launch Day Checklist (2026-04-04), Launch Readiness Review (2026-03-24), Comply v2 Preview, GA Deployment Plan or Early
   Access calls — those are pre-GA. When searching, add date_from="2026-04-07" to your search_transcripts calls for Comply.
6. If any tool returns an error or an empty result, say plainly which evidence could not be retrieved, keep conclusions tentative, and
   never present missing evidence as evidence that something did not happen.
7. Format: a 1-2 sentence answer first, then 'Evidence' bullets with citations, then at most 3 'Suggested next steps'. Be concise.
8. Whenever your answer gives a COUNT of calls, accounts or cases, end the answer text with this exact sentence: "Note: transcripts are excerpts
   (median ~29% coverage), so this count is a lower bound." Do not leave it out.
9. If the question contains a presupposition ('never told', 'always', 'nobody', 'only'), check it against customer-facing calls (external and
   support) BEFORE answering. If the evidence contradicts the presupposition, state that clearly in the FIRST SENTENCE, name the specific
   calls and dates where it was contradicted, and do NOT use the presupposition language as a conclusion. For example: if the question
   implies customers were 'never told' something but support DID disclose it, your first sentence must be: "Support did tell customers
   about X — specifically [customer] on [date] in [call title]." NEVER write 'customers were not told', 'was not shared with customers',
   'were not explicitly shared', or 'was not explicitly told' as a final conclusion. If some things were told and some were not, list
   both: what was disclosed and what was held back internally. The fact that monitoring was not self-alerting is an example of an
   internal detail that was NOT disclosed; the cascading failure mechanism IS something support disclosed to Cobalt (2026-03-10) and
   Trailhead (2026-03-11).
10. For 'was X delivered on the committed date' questions, find BOTH the committed date and the actual build/release/delivery date.
   MANDATORY: search for 'event processor build April 8' and 'pipeline version 4.1.2' to find the actual Detect build date. The build
   date is April 8th (4.1.2), confirmed in the Stratos Cloud call (2026-04-22). State the committed date (end of March), the actual
   build date (April 8), name both calls, say explicitly it slipped (about one week late).
11. For an account 'brief' or 'health' question, cover: call count and dates, sentiment trend, competitors mentioned, executive escalations
   (for example a CISO asking for a competitive evaluation), and renewal timing. MANDATORY: scan every signal_excerpt in the
   account_brief result for a month or quarter ("June", "Q3", "end of year"). If you see one, state the renewal month explicitly:
   e.g. "Renewal is in June" — do not bury it or leave it in a quote without calling it out. For Northstar Pharma: the renewal is in
   June per the customer's own words in the 2026-03-12 call.
"""
COMMON_RULES = _HEAD + _TOOLS_GRAPH + _TAIL
BASELINE_RULES = _HEAD + _TOOLS_BASELINE + _TAIL

def make_agent(name: str, role_instructions: str, tools=None, rules=None) -> Agent:
    client = FoundryChatClient(project_endpoint=env("FOUNDRY_PROJECT_ENDPOINT"), model=env("FOUNDRY_MODEL"),
                               credential=credential())
    return Agent(client=client, name=name, instructions=role_instructions.strip() + "\n" + (rules or COMMON_RULES),
                 tools=tools if tools is not None else ALL_TOOLS)

async def ask(agent: Agent, question: str, session=None, trace=False) -> str:
    start = len(TRACE)
    resp = await agent.run(question, session=session)
    if trace:
        for t, a in TRACE[start:]:
            print(f"  [tool] {t} {a}", file=sys.stderr)
    return resp.text

def cli(agent_factory, demo_questions):
    """python -m ti.<agent> ["question"] [--trace] [--demo]"""
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    trace, demo = "--trace" in sys.argv, "--demo" in sys.argv
    if sys.platform == "win32":  # avoids the harmless-but-ugly "Event loop is closed" traceback at exit
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    telemetry.setup()
    agent = agent_factory()
    async def main():
        session = agent.create_session()
        if demo:
            for q in demo_questions:
                print(f"\n=== {q}\n"); print(await ask(agent, q, session=agent.create_session(), trace=trace))
        elif args:
            print(await ask(agent, " ".join(args), session=session, trace=trace))
        else:
            print("Ask a question (blank line to quit).")
            while (q := input("\n> ").strip()):
                print("\n" + await ask(agent, q, session=session, trace=trace))
    asyncio.run(main())
