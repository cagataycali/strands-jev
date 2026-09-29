"""align_entities, classify_hierarchical, recover_structure, guardrail, pick_from_catalog, consistency_check."""

from __future__ import annotations

from typing import Any

from strands import Agent
from strands.models import BedrockModel
from typesafe_sdk import Noul, Score

from strands_jev import (
    ALL_TOOLS,
    align_entities,
    classify_hierarchical,
    consistency_check,
    guardrail,
    pick_from_catalog,
    recover_structure,
)
from strands_jev.questions import ALIGN_LEVELS, GUARD_SEVERITY_LEVELS, NO_MATCH
from strands_jev.tools.cookbooks_more import render_markdown, stitch_lines
from tests.conftest import FakeJev, choice, noul, payload, score, summary


def _ctx(fake: FakeJev) -> Any:
    class Ctx:
        invocation_state = {"jev": fake}

    return Ctx()


# ------------------------------------------------------------------------ align_entities

PAIRS = [
    {
        "left": {"name": "Pliny the Elder", "brewery": "Russian River"},
        "right": {"name": "Pliny the Elder", "brewery": "Russian River Brewing"},
    },
    {
        "left": {"name": "Pliny the Elder", "brewery": "Russian River"},
        "right": {"name": "Pliny the Younger", "brewery": "Russian River"},
    },
    {
        "left": {"name": "Guinness Draught", "brewery": "Guinness"},
        "right": {"name": "Pliny the Elder", "brewery": "Russian River"},
    },
]


async def test_align_entities_maps_levels_to_outcomes_with_field_nouls() -> None:
    def responder(state: Any, questions: Any) -> dict[str, Any]:
        left, right = state["left"], state["right"]
        level = 2.0 if left["name"] == right["name"] else 1.0 if left["brewery"] == right["brewery"] else 0.0
        return {
            "relation": score(level, ALIGN_LEVELS),
            "same_name": noul(0.95 if level == 2 else 0.1),
            "same_brewery": noul(0.9 if level else 0.05),
        }

    fake = FakeJev(responder=responder)
    result = await align_entities(pairs=PAIRS, fields=["name", "brewery"], tool_context=_ctx(fake))
    body = payload(result)
    assert fake.call_count == 3
    assert [row["outcome"] for row in body["results"]] == ["same", "review", "leave_unlinked"]
    assert body["results"][1]["disagree"] == ["name"]
    assert body["counts"] == {"same": 1, "review": 1, "leave_unlinked": 1}
    assert summary(result) == "leave_unlinked 1, review 1, same 1"
    assert isinstance(fake.last_questions["relation"], Score) and isinstance(fake.last_questions["same_name"], Noul)
    assert fake.last_questions["same_brewery"].instructions == "Do the two entities state the same brewery?"


async def test_align_entities_refusals(fake: FakeJev) -> None:
    assert "needs left and right" in summary(await align_entities(pairs=[{"left": 1}], tool_context=_ctx(fake)))
    assert "exactly three" in summary(await align_entities(pairs=PAIRS, levels=["a", "b"], tool_context=_ctx(fake)))
    assert fake.call_count == 0


# ----------------------------------------------------------------- classify_hierarchical

TAXONOMY = {
    "hardware": {
        "description": "Physical devices",
        "children": {"laptops": "Portable computers", "phones": "Mobile phones"},
    },
    "software": {
        "description": "Programs",
        "children": {
            "os": "Operating systems",
            "apps": {"description": "Applications", "children": {"games": "Games", "office": "Office suites"}},
        },
    },
}


async def test_classify_hierarchical_descends_to_a_leaf() -> None:
    def responder(state: Any, questions: Any) -> dict[str, Any]:
        options = list(questions["child"].criteria)
        if "software" in options:
            return {"child": choice("software", {"software": 0.9, "hardware": 0.05, NO_MATCH: 0.05})}
        if "apps" in options:
            return {"child": choice("apps", {"apps": 0.8, "os": 0.15, NO_MATCH: 0.05})}
        return {"child": choice("games", {"games": 0.95, "office": 0.05, NO_MATCH: 0.0})}

    fake = FakeJev(responder=responder)
    result = await classify_hierarchical(
        document="A new racing game for the console", taxonomy=TAXONOMY, tool_context=_ctx(fake)
    )
    body = payload(result)
    assert body["path"] == ["software", "apps", "games"] and body["leaf"]
    assert fake.call_count == 3 and len(body["levels"]) == 3
    assert summary(result) == "software > apps > games"
    assert NO_MATCH in fake.calls[0][1]["child"].criteria


async def test_classify_hierarchical_stops_on_low_confidence_or_no_match() -> None:
    fake = FakeJev(
        [
            {"child": choice("hardware", {"hardware": 0.9, "software": 0.1, NO_MATCH: 0.0})},
            {"child": choice("laptops", {"laptops": 0.5, "phones": 0.45, NO_MATCH: 0.05})},
        ]
    )
    result = await classify_hierarchical(document="x", taxonomy=TAXONOMY, tool_context=_ctx(fake))
    body = payload(result)
    assert body["path"] == ["hardware"] and not body["leaf"] and "under the 0.60 floor" in body["stopped_because"]
    fake = FakeJev({"child": choice(NO_MATCH, {NO_MATCH: 0.8, "hardware": 0.1, "software": 0.1})})
    result = await classify_hierarchical(document="x", taxonomy=TAXONOMY, tool_context=_ctx(fake))
    assert payload(result)["path"] == [] and summary(result).startswith("unclassified (no category fits")


# -------------------------------------------------------------------- recover_structure


def test_stitch_lines_thresholds() -> None:
    lines = ["Install the package", "with pip.", "Then run it.", "Twice."]
    joins = {1: 0.3, 2: 0.3, 3: 0.6}
    # dangling first line merges at 0.3 (cut 0.2); after a terminal line 0.3 does not merge (cut 0.5); 0.6 does.
    assert stitch_lines(lines, joins) == ["Install the package with pip.", "Then run it. Twice."]


def test_render_markdown_groups_lists_and_headings() -> None:
    blocks = [
        {"text": "Setup", "type": "heading", "heading_level": "title", "step": 0.0, "callout": None},
        {"text": "Do this first", "type": "list_item", "step": 0.9},
        {"text": "Then this", "type": "list_item", "step": 0.8},
        {"text": "Mind the gap", "type": "callout", "callout": "warning", "step": 0.0},
        {"text": "pip install x", "type": "code", "step": 0.0},
        {"text": "Some prose.", "type": "paragraph", "step": 0.0},
    ]
    md = render_markdown(blocks)
    assert md.startswith("# Setup\n\n1. Do this first\n2. Then this\n\n> **WARNING:** Mind the gap\n\n")
    assert md.endswith("```\npip install x\n```\n\nSome prose.\n")


async def test_recover_structure_two_passes() -> None:
    text = "Quick start\nInstall the package with\npip and then run it.\n\nDo this first\nThen do that"

    def responder(state: Any, questions: Any) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        for key in questions:
            if key.startswith("L"):
                answers[key] = noul(0.9 if key == "L003" else 0.05)
            elif key.startswith("type_"):
                bid = key[5:]
                kind = {"B001": "heading", "B002": "paragraph"}.get(bid, "list_item")
                answers[key] = choice(kind, {kind: 0.9})
            elif key.startswith("hlevel_"):
                answers[key] = choice("title", {"title": 0.8})
            elif key.startswith("step_"):
                answers[key] = noul(0.8)
            else:
                answers[key] = choice("note", {"note": 0.6})
        return answers

    fake = FakeJev(responder=responder)
    result = await recover_structure(text=text, tool_context=_ctx(fake))
    body = payload(result)
    assert body["requests"] == 2 and body["blocks_out"] == 4
    assert body["blocks"][1]["text"] == "Install the package with pip and then run it."
    assert (
        body["markdown"]
        == "# Quick start\n\nInstall the package with pip and then run it.\n\n1. Do this first\n2. Then do that\n"
    )
    assert fake.calls[0][0].startswith("L001| Quick start\nL002| Install")
    assert set(fake.calls[0][1]) == {"L002", "L003", "L006"}  # L005 follows a blank line: no join question
    assert summary(result).startswith("5 lines -> 4 blocks in 2 requests")
    assert "text is empty" in summary(await recover_structure(text="\n\n", tool_context=_ctx(fake)))


# ----------------------------------------------------------------------------- guardrail


def _battery(**p: float) -> dict[str, Any]:
    base = {"jailbreak": 0.02, "harmful_request": 0.02, "medical_advice": 0.02, "self_harm": 0.02}
    base.update(p)
    answers: dict[str, Any] = {k: noul(v) for k, v in base.items()}
    answers["severity"] = score(p.get("sev", 0.1), GUARD_SEVERITY_LEVELS)
    return answers


async def test_guardrail_pass_review_and_action() -> None:
    fake = FakeJev(_battery())
    result = await guardrail(message="what is the capital of France?", tool_context=_ctx(fake))
    assert payload(result)["decision"] == "pass" and summary(result) == "pass"
    assert len(fake.last_questions) == 5 and isinstance(fake.last_questions["severity"], Score)

    fake = FakeJev(_battery(medical_advice=0.5, sev=1.0))
    body = payload(await guardrail(message="m", tool_context=_ctx(fake)))
    assert body["decision"] == "review" and body["review"] == ["medical_advice"]

    fake = FakeJev(_battery(medical_advice=0.5, sev=2.4))
    assert payload(await guardrail(message="m", tool_context=_ctx(fake)))["decision"] == "block"

    fake = FakeJev(_battery(jailbreak=0.9, sev=1.5))
    result = await guardrail(message="m", policy={"actions": {"jailbreak": "refuse"}}, tool_context=_ctx(fake))
    assert payload(result)["decision"] == "refuse" and summary(result) == "refuse: jailbreak 0.90"

    fake = FakeJev(_battery(self_harm=0.35))
    body = payload(
        await guardrail(message="m", policy={"thresholds": {"self_harm": {"action": 0.3}}}, tool_context=_ctx(fake))
    )
    assert body["fired"] == ["self_harm"]


async def test_guardrail_output_side_and_refusals(fake: FakeJev) -> None:
    await guardrail(message="reply", side="output", tool_context=_ctx(fake))
    assert "broke_policy" in fake.last_questions
    assert "side must be input or output" in summary(await guardrail(message="m", side="both", tool_context=_ctx(fake)))
    assert "must not exceed" in summary(
        await guardrail(message="m", policy={"action": 0.3, "review": 0.5}, tool_context=_ctx(fake))
    )
    assert "not in the input battery" in summary(
        await guardrail(message="m", policy={"actions": {"broke_policy": "x"}}, tool_context=_ctx(fake))
    )
    assert fake.call_count == 1


# ---------------------------------------------------------------------- pick_from_catalog

CATALOG = {
    "git-rebase": {"description": "Rewrite git history", "details": "Interactive rebase, squash, reorder commits."},
    "docker-compose": "Run multi-container apps",
    "aws-iam": "Manage AWS permissions",
    "kubectl": "Operate Kubernetes clusters",
    "poetry": "Python packaging with Poetry",
    "vim-motions": "Edit text faster in vim",
}


async def test_pick_from_catalog_two_requests_and_pick() -> None:
    fake = FakeJev(
        [
            {
                "which": choice(
                    "git-rebase",
                    {
                        "git-rebase": 0.5,
                        "kubectl": 0.2,
                        "poetry": 0.1,
                        "docker-compose": 0.1,
                        "aws-iam": 0.05,
                        "vim-motions": 0.05,
                    },
                ),
                "gate_acts_on_user_resources": noul(0.9),
                "gate_would_follow_documented_procedure": noul(0.8),
                "gate_prose_suffices": noul(0.1),
            },
            {
                "which": choice("git-rebase", {"git-rebase": 0.85, "kubectl": 0.1, "poetry": 0.05}),
                "fits_git-rebase": noul(0.9),
                "fits_kubectl": noul(0.1),
                "fits_poetry": noul(0.1),
            },
        ]
    )
    result = await pick_from_catalog(
        request="squash my last three commits into one", catalog=CATALOG, top_k=3, tool_context=_ctx(fake)
    )
    body = payload(result)
    assert fake.call_count == 2 and body["pick"] == "git-rebase" and body["fits"] == 0.9
    assert [row["name"] for row in body["shortlist"]] == ["git-rebase", "kubectl", "poetry"]
    assert body["gates"]["prose_suffices"]["points_to_catalog"] is True
    assert (
        fake.calls[1][1]["which"].criteria["git-rebase"]
        == "Rewrite git history Interactive rebase, squash, reorder commits."
    )
    assert summary(result) == "git-rebase (0.85, fits 0.9)"


async def test_pick_from_catalog_none_when_gated_out_or_unfit() -> None:
    first = {
        "which": choice(
            "vim-motions",
            {
                "vim-motions": 0.3,
                "git-rebase": 0.2,
                "kubectl": 0.2,
                "poetry": 0.1,
                "docker-compose": 0.1,
                "aws-iam": 0.1,
            },
        ),
        "gate_acts_on_user_resources": noul(0.1),
        "gate_would_follow_documented_procedure": noul(0.2),
        "gate_prose_suffices": noul(0.9),
    }
    second = {
        "which": choice("vim-motions", {"vim-motions": 0.7, "git-rebase": 0.3}),
        "fits_vim-motions": noul(0.6),
        "fits_git-rebase": noul(0.1),
    }
    fake = FakeJev([first, second])
    result = await pick_from_catalog(request="what is a monad?", catalog=CATALOG, top_k=2, tool_context=_ctx(fake))
    assert payload(result)["pick"] is None and "gates point away" in summary(result)
    fake = FakeJev([dict(first, gate_prose_suffices=noul(0.1)), dict(second, **{"fits_vim-motions": noul(0.2)})])
    result = await pick_from_catalog(request="q", catalog=CATALOG, top_k=2, tool_context=_ctx(fake))
    assert payload(result)["pick"] is None and summary(result) == "none: best vim-motions at 0.70, fits 0.2"


async def test_pick_from_catalog_refusals(fake: FakeJev) -> None:
    assert "at least two" in summary(
        await pick_from_catalog(request="q", catalog={"only": "one"}, tool_context=_ctx(fake))
    )
    assert "between 1 and 20" in summary(
        await pick_from_catalog(request="q", catalog=CATALOG, top_k=50, tool_context=_ctx(fake))
    )
    assert fake.call_count == 0


# ------------------------------------------------------------------- consistency_check


async def test_consistency_check_repeats_and_review() -> None:
    fake = FakeJev(
        [
            {
                "safe": noul(0.9),
                "team": choice("a", {"a": 0.55, "b": 0.45}),
                "sev": score(1.0, ["l", "m", "h"], {0: 0.1, 1: 0.8, 2: 0.1}),
            },
            {
                "safe": noul(0.55),
                "team": choice("a", {"a": 0.9, "b": 0.1}),
                "sev": score(1.2, ["l", "m", "h"], {0: 0.0, 1: 0.8, 2: 0.2}),
            },
        ]
    )
    result = await consistency_check(
        state="x",
        questions={
            "safe": "is it safe?",
            "team": {"type": "choice", "instructions": "t", "criteria": ["a", "b"]},
            "sev": {"type": "score", "instructions": "s", "criteria": ["l", "m", "h"]},
        },
        repeats=2,
        tool_context=_ctx(fake),
    )
    body = payload(result)
    assert fake.call_count == 2 and body["repeats"] == 2
    assert (
        body["answers"]["safe"]["value"] is True
        and body["answers"]["safe"]["agreement"] == 1.0
        and not body["answers"]["safe"]["decided"]
    )
    assert body["answers"]["team"]["decided"] is False  # first repeat under the 0.6 floor
    assert body["answers"]["sev"]["decided"] is True and body["answers"]["sev"]["value"] == 1
    assert body["review"] == ["safe", "team"]
    assert summary(result) == "1/3 decided; review: safe, team (2 repeats)"
    assert "between 1 and 5" in summary(
        await consistency_check(state="x", questions=["q"], repeats=9, tool_context=_ctx(fake))
    )


def test_direct_agent_calls_for_every_second_shelf_tool() -> None:
    agent = Agent(
        model=BedrockModel(model_id="never-called", region_name="us-east-1"), tools=ALL_TOOLS, callback_handler=None
    )
    assert len(ALL_TOOLS) == 19
    fake = FakeJev({"relation": score(2.0, ALIGN_LEVELS)})
    assert (
        payload(agent.tool.align_entities(pairs=[{"left": "a", "right": "a"}], jev=fake))["results"][0]["outcome"]
        == "same"
    )
    fake = FakeJev({"child": choice("hardware", {"hardware": 0.9, "software": 0.1, NO_MATCH: 0.0})})
    assert payload(
        agent.tool.classify_hierarchical(document="d", taxonomy={"hardware": "h", "software": "s"}, jev=fake)
    )["path"] == ["hardware"]
    fake = FakeJev({"type_B001": choice("paragraph", {"paragraph": 1.0})})
    assert payload(agent.tool.recover_structure(text="one line", jev=fake))["markdown"] == "one line\n"
    assert payload(agent.tool.guardrail(message="hi", jev=FakeJev(_battery())))["decision"] == "pass"
    fake = FakeJev([{"which": choice("a", {"a": 0.9, "b": 0.1})}, {"fits_a": noul(0.9)}])
    assert (
        payload(
            agent.tool.pick_from_catalog(request="r", catalog={"a": "A", "b": "B"}, top_k=1, gates=False, jev=fake)
        )["pick"]
        == "a"
    )
    assert payload(agent.tool.consistency_check(state="s", questions=["q"], jev=FakeJev({"q1": noul(0.95)})))[
        "answers"
    ]["q1"]["decided"]
