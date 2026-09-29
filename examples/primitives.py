"""The raw call: an agent asks Jev three typed questions about one ticket.

Run: python examples/primitives.py   (needs AWS credentials for the agent's model and a Jev key)
"""

from __future__ import annotations

from strands import Agent
from strands.models import BedrockModel

from strands_jev import PRIMITIVE_TOOLS

TICKET = "Help! My payouts have been failing for 3 days."

agent = Agent(
    model=BedrockModel(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    tools=PRIMITIVE_TOOLS,
    callback_handler=None,
    system_prompt=(
        "You have jev_ask, which answers typed questions (noul, choice, score) about a piece of text with "
        "calibrated probabilities. Use it instead of guessing when asked to judge a ticket."
    ),
)

result = agent(
    f"Judge this ticket with jev_ask: is it urgent (noul), which team (choice: billing, technical, sales), "
    f"how frustrated is the customer (score: calm, frustrated, very angry)? Report the numbers. Ticket: {TICKET!r}"
)
print(result)
print(agent.tool.jev_usage()["content"][-1]["text"])
