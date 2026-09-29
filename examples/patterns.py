"""Direct tool calls, no chat model: route a message, then fill a function call from a request.

Run: python examples/patterns.py   (needs a Jev key in TYPESAFE_API_KEY or ~/.typesafe)
"""

from __future__ import annotations

import json

from strands import Agent
from strands.models import BedrockModel

from strands_jev import PATTERN_TOOLS

agent = Agent(model=BedrockModel(model_id="never-called"), tools=PATTERN_TOOLS, callback_handler=None)

routed = agent.tool.route(
    message="Second time the driver did not ring. Box left in the rain. I want this fixed today.",
    intents={
        "order_status": "Where an order is, tracking, delivery dates",
        "return_exchange": "Sending an item back or swapping it",
        "complaint": "Something went wrong and the customer wants it put right",
    },
    handlers={"order_status": "code", "return_exchange": "returns_llm", "complaint": "complaint_llm"},
    complex_intents=["complaint"],
)
print(routed["content"][-1]["text"])

call = agent.tool.function_call(
    request="candles for tesla with volume",
    functions={
        "plot_price": {
            "description": "Draw a price chart for one ticker",
            "arguments": {
                "symbol": {
                    "question": "Which company is the chart about?",
                    "options": {"TSLA": "Tesla", "AAPL": "Apple"},
                },
                "style": {
                    "question": "A plain line or candles?",
                    "stated": "Does the user say how the chart should be drawn, such as a line, candles or OHLC bars?",
                    "options": {"line": "a line", "candles": "candlesticks"},
                },
                "include_volume": {"question": "Does the user want volume shown?", "kind": "flag"},
            },
        },
        "list_symbols": "List the tickers the assistant knows",
    },
)
print(call["content"][-1]["text"])
print(json.dumps(call["content"][0]["json"]["per_argument"], indent=2))
