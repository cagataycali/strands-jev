"""Direct tool calls: re-rank a shortlist, find the line that answers a question, pick a value.

Run: python examples/cookbooks.py   (needs a Jev key in TYPESAFE_API_KEY or ~/.typesafe)
"""

from __future__ import annotations

from strands import Agent
from strands.models import BedrockModel

from strands_jev import COOKBOOK_TOOLS

agent = Agent(model=BedrockModel(model_id="never-called"), tools=COOKBOOK_TOOLS, callback_handler=None)

PASSAGES = [
    "Refund requests made within 14 days of purchase are honoured in full.",
    "The refund policy page lists the customer service opening hours.",
    "Accounts are suspended after three failed payment attempts.",
]
print(
    agent.tool.rerank(query="Can I get my money back a week after buying?", candidates=PASSAGES, top_k=1)["content"][
        -1
    ]["text"]
)

TERMS = "\n".join(
    [
        "1. Fees",
        "Fees are invoiced monthly in arrears.",
        "Late payments accrue interest at 1.5% per month.",
        "2. Law",
        "Irish law.",
    ]
)
print(
    agent.tool.find_lines(
        document=TERMS, queries=["Is there a penalty for paying late?", "What is the uptime guarantee?"]
    )["content"][-1]["text"]
)

MAIL = "From: ana@x.io. Could you send the receipt to my personal address bob.k@gmail.com rather than this one?"
print(
    agent.tool.extract_value(document=MAIL, question="Which address should the receipt go to?", kind="email")[
        "content"
    ][-1]["text"]
)

print(
    agent.tool.extract_date(document="Let's meet next Thursday at 10.", role="the meeting date", today="2026-09-29")[
        "content"
    ][-1]["text"]
)
