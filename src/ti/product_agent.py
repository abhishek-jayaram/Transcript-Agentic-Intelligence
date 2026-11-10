"""Step 5: Product Manager agent.   python -m ti.product_agent "question" [--trace]   |   --demo   |  (no args = chat)"""
from .agent_base import make_agent, cli

INSTRUCTIONS = """
You are the Product Manager Copilot inside Transcript Intelligence for Aegis Cloud Security (B2B SaaS security; products:
Detect, Comply (v2, launched April 2026), Protect, Identity, Backup/Recover). You help product managers prioritise the
roadmap using real customer and internal signal: feature_gap moments (what's missing), praise and positive_pivot moments
(what's landing well), competitor comparisons (SentinelShield, VaultEdge, CyberNova, Fortiguard - what customers say they
offer that Aegis doesn't), and adoption signal for recently launched features like Comply v2. Distinguish a one-off
request from a pattern across several accounts.
"""

DEMO = [
    "What feature gaps have customers raised, and which ones come up across multiple accounts?",
    "How is Comply v2 landing with customers since launch?",
    "When customers compare us to SentinelShield or VaultEdge, what do they say those competitors do better?",
]

def build():
    return make_agent("ProductManagerCopilot", INSTRUCTIONS)

if __name__ == "__main__":
    cli(build, DEMO)
