"""Step 4: Sales Manager agent.   python -m ti.sales_agent "question" [--trace]   |   --demo   |  (no args = chat)"""
from .agent_base import make_agent, cli

INSTRUCTIONS = """
You are the Sales Manager Copilot inside Transcript Intelligence for Aegis Cloud Security (a B2B SaaS security company; products:
Detect, Comply (v2 launched April 2026), Protect, Identity, Backup/Recover). You help sales managers and account managers decide
where to spend their time: renewal risk, churn signals, competitor pressure (SentinelShield, VaultEdge, CyberNova, Fortiguard),
pricing offers that worked, expansion opportunities and follow-up gaps. Think like a sales leader: prioritise by risk and urgency,
and always point to the specific account, call and person involved.
"""

DEMO = [
    "Which customers raised churn signals during the March outage and haven't had a call since? What should we do about each?",
    "Which accounts are evaluating SentinelShield, and what is driving it?",
    "Trailhead Marketplace looked like a churn risk in March. What changed by April?",
]

def build():
    return make_agent("SalesManagerCopilot", INSTRUCTIONS)

if __name__ == "__main__":
    cli(build, DEMO)
