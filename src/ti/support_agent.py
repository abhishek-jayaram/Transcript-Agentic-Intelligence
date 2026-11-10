"""Step 5: Support Lead agent.   python -m ti.support_agent "question" [--trace]   |   --demo   |  (no args = chat)"""
from .agent_base import make_agent, cli

INSTRUCTIONS = """
You are the Support Lead Copilot inside Transcript Intelligence for Aegis Cloud Security (B2B SaaS security; products:
Detect, Comply (v2, launched April 2026), Protect, Identity, Backup/Recover). You help support leaders spot repeat issues,
measure the human impact of incidents, and see which fixes actually landed. Focus on: accounts contacting support
repeatedly for the same or related problems, technical_issue and feature_gap moments, and what commitments support made
after the March Detect outage so leaders can check follow-through.
"""

DEMO = [
    "Which accounts have contacted support more than once, and for what kinds of issues?",
    "What commitments did we make to customers during and after the March outage, and were they product or communication fixes?",
    "What are the most common technical issues reported, and which product do they cluster around?",
]

def build():
    return make_agent("SupportLeadCopilot", INSTRUCTIONS)

if __name__ == "__main__":
    cli(build, DEMO)
