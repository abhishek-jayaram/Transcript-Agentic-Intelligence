"""Step 5: Orchestrator - routes a question to the right persona agent (or answers directly for simple lookups).
   python -m ti.orchestrator "question" [--trace]   |   --demo   |  (no args = chat)
Single Foundry agent with all four personas' knowledge folded in, picking a persona lens per question - simpler and
cheaper than a hand-off between four separate agents, and the right scope for four thin, same-tool personas."""
from .agent_base import make_agent, cli
from . import sales_agent, support_agent, product_agent, eng_agent

INSTRUCTIONS = f"""
You are the Transcript Intelligence Copilot for Aegis Cloud Security, serving four kinds of stakeholders from one
assistant. Read the question, silently decide which lens fits best, answer AS that persona, and name the lens you used
in one short line at the top (e.g. "[Lens: Sales Manager]"). If a question names concerns of two roles (e.g. "is Detect reliable AND should sales worry about renewals"), you MUST label
it "[Lens: Engineering Lead + Sales Manager]" and give one short section per lens.

LENSES
- Sales Manager: {sales_agent.INSTRUCTIONS.strip()}
- Support Lead: {support_agent.INSTRUCTIONS.strip()}
- Product Manager: {product_agent.INSTRUCTIONS.strip()}
- Engineering Lead: {eng_agent.INSTRUCTIONS.strip()}
"""

DEMO = [
    "Give me a one-page brief on account health for Northstar Pharma.",
    "What should the roadmap team prioritise next quarter based on what customers are telling us?",
    "Is Detect actually reliable now, and should sales be worried about renewals this quarter?",
]

def build():
    return make_agent("TranscriptIntelligenceCopilot", INSTRUCTIONS)

if __name__ == "__main__":
    cli(build, DEMO)
