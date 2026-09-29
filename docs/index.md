---
hide: [navigation, toc]
template_class: sj-home
---

# Strands Jev

<div class="sj-hero" markdown>
<div markdown>
<p class="sj-hero__title">Typed questions. <em>Calibrated answers.</em></p>
<p class="sj-hero__lead">Jev is TypeSafe's System One model: it reads one piece of state and answers yes/no, pick-one and rate-it questions with probabilities, in one request, without generating a word. These tools let a Strands Agent ask it. The chat model proposes; Jev decides.</p>
<div class="sj-hero__actions">
<a class="sj-btn sj-btn--primary" href="start/">Start</a>
<a class="sj-btn" href="tools/">The tools</a>
<span class="sj-install">pip install git+https://github.com/cagataycali/strands-jev<button class="sj-copy" data-clipboard-text="pip install git+https://github.com/cagataycali/strands-jev">copy</button></span>
</div>
</div>
<div class="sj-stage" aria-label="One request, three typed answers">
<div class="sj-stage__request">
<span class="sj-stage__label">state</span>
<p class="sj-stage__state">Help! My payouts have been failing for 3 days.</p>
<span class="sj-stage__label">questions</span>
<ul class="sj-stage__questions">
<li><span class="sj-kind">noul</span> Does this convey urgency?</li>
<li><span class="sj-kind">choice</span> Which team? <span class="sj-dim">billing · technical · sales</span></li>
<li><span class="sj-kind">score</span> How frustrated is the writer? <span class="sj-dim">calm · frustrated · very angry</span></li>
</ul>
</div>
<div class="sj-stage__answers">
<span class="sj-stage__label">answers</span>
<div class="sj-answer"><span class="sj-answer__key">urgent</span><span class="sj-bar" style="--p: 95%"></span><strong>0.95</strong></div>
<div class="sj-answer"><span class="sj-answer__key">team</span><span class="sj-answer__value">billing</span><strong>0.98</strong></div>
<div class="sj-answer"><span class="sj-answer__key">frustration</span><span class="sj-answer__value">frustrated</span><strong>0.94</strong></div>
<p class="sj-stage__foot">one request, 178 ms, 434 input tokens, recorded 2026-09-29 against jev-1.13.0</p>
</div>
</div>
</div>

<div class="sj-proof" markdown>
<div><strong>{{n:tools}}</strong><span>tools an agent can call, in {{n:groups}} groups</span></div>
<div><strong>{{n:live_cases}}</strong><span>live cases measured against a code baseline: Jev {{n:live_jev_correct}}, baseline {{n:live_baseline_correct}}</span></div>
<div><strong>{{n:live_mean_ms}}</strong><span>ms mean latency per request across {{n:live_calls}} live calls</span></div>
</div>

<div class="sj-grid" markdown>
<div class="sj-card" markdown>
### [Start](start/index.md)
Install, put the key in place, make one decision from Python, hand the tools to an agent, read the bill.
</div>
<div class="sj-card" markdown>
### [Learn](learn/index.md)
System One in one page. Noul, Choice and Score. State, confidence, the patterns, and what not to ask.
</div>
<div class="sj-card" markdown>
### [Tools](tools/index.md)
Every `@tool`, generated from the specs the agent reads: parameters, result shape, the docs page it ports, its live score.
</div>
<div class="sj-card" markdown>
### [Measured](measured/index.md)
Every tool against the deterministic code a developer would write instead. Real numbers, real cost, dated and versioned.
</div>
<div class="sj-card" markdown>
### [Project](project/index.md)
The design grid, key handling and what leaves the machine, the changelog, how to contribute.
</div>
</div>

## One call, any mix of questions

```python
from strands import Agent
from strands_jev import ALL_TOOLS

agent = Agent(tools=ALL_TOOLS)
result = agent.tool.jev_ask(
    state="Help! My payouts have been failing for 3 days.",
    questions={
        "urgent": {"type": "noul", "instructions": "Does this convey urgency?"},
        "team": {"type": "choice", "instructions": "Which team?", "criteria": {"billing": "payments", "technical": "bugs", "sales": "plans and pricing"}},
        "frustration": {"type": "score", "instructions": "How frustrated is the writer?", "criteria": ["calm", "frustrated", "very angry"]},
    },
)
print(result["content"][1]["text"])
```

The direct call skips the chat model. `agent("Is this ticket urgent, and who should take it?")` lets the model pick the tool and write the questions itself. Either way the request is one HTTP call billed at ${{n:price_per_mtok}} per million input tokens, output free. [Start here](start/index.md).
