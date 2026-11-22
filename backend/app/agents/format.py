"""One reply shape for every message GOIP posts in the Switch room.

Switch renders Markdown. Every reply is a small card: a heading, optional lead sentence, labelled fields,
a table or bullet list, a quoted note, and a next step. Keeping this in one module is what makes the room read
as one product instead of seven voices.
"""

from __future__ import annotations

NO_OUTREACH = "No outreach was sent."


def cell(value: object, limit: int = 90) -> str:
    """Make a value safe inside a Markdown table cell."""
    text = " ".join(str(value if value is not None else "").split())
    text = text.replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def link(label: object, url: str | None) -> str:
    if not url or not str(url).startswith(("http://", "https://")):
        return cell(label)
    return f"[{cell(label, 60)}]({str(url).replace(')', '%29').replace(' ', '%20')})"


def code(value: object) -> str:
    return f"`{str(value).replace('`', '')}`"


def label(value: object) -> str:
    return str(value or "").replace("_", " ")


def table(headers: list[str], rows: list[list[object]]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "|" + "|".join("---" for _ in headers) + "|"
    body = ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def card(
    title: str,
    *,
    lead: str | None = None,
    fields: list[tuple[str, object]] | None = None,
    grid: str | None = None,
    bullets: list[str] | None = None,
    quote: str | None = None,
    note: str | None = None,
    next_step: str | None = None,
) -> str:
    parts = [f"#### {title}"]
    if lead:
        parts.append(lead)
    if fields:
        parts.append("\n".join(f"- **{k}:** {v}" for k, v in fields if v not in (None, "")))
    if grid:
        parts.append(grid)
    if bullets:
        parts.append("\n".join(f"- {b}" for b in bullets))
    if quote:
        parts.append("> " + str(quote).replace("\n", "\n> "))
    if note:
        parts.append(f"*{note}*")
    if next_step:
        parts.append(f"**Next:** {next_step}")
    return "\n\n".join(p for p in parts if p)


STAGE_NAME = {"discover": "Discovery", "research": "Research", "technical": "Technical", "qualify": "Qualification", "strategy": "Strategy", "qa": "Quality"}


def stage_line(stage: str, summary: str, mode: str | None = None, note: str | None = None) -> str:
    """A readable progress line for the room, from a stage's JSON/text summary.

    `mode` says whether the agent's model ran ("llm") or its fixed policy did ("fallback"); `note` is its one-line reason.
    """
    line = _stage_core(stage, summary)
    tag = {"llm": " · *model decided*", "fallback": " · *fixed policy*"}.get(mode or "", "")
    out = line + tag
    if note:
        out += "\n> " + " ".join(str(note).split())[:280]
    return out


def _stage_core(stage: str, summary: str) -> str:
    import json
    import re

    name = STAGE_NAME.get(stage, stage)
    try:
        data = json.loads(summary)
    except (TypeError, ValueError):
        data = None
    if stage == "discover" and isinstance(data, dict):
        extra = f" · focus **{data['focus']}**" if data.get("focus") else ""
        hiring = f" · **{data['hiring_posts']}** hiring posts" if data.get("hiring_posts") else ""
        return (f"✓ **{name}**: read **{data.get('raw_items', 0)}** items, **{data.get('discovered', 0)}** companies "
                f"({data.get('duplicate_signals', 0)} already stored){hiring}{extra}")
    if stage == "research":
        found = re.search(r"(\d+)", summary or "")
        return f"✓ **{name}**: quoted the source for **{found.group(1) if found else '0'}** companies"
    if stage == "technical" and isinstance(data, dict):
        return f"✓ **{name}**: checked **{data.get('repositories_seen', 0)}** repositories, matched **{data.get('attached', 0)}**"
    if stage == "qualify" and isinstance(data, dict):
        return f"✓ **{name}**: **{data.get('qualified', 0)}** qualified, **{data.get('high_priority', 0)}** high priority"
    if stage == "strategy":
        return f"✓ **{name}**: service notes recorded. Nothing was drafted or sent"
    if stage == "qa" and isinstance(data, dict):
        return f"✓ **{name}**: **{data.get('qa_flags', 0)}** QA flag(s)"
    return f"✓ **{name}**: {str(summary)[:200]}"


def plan_card(plan) -> str:
    how = "the model planned this run" if plan.mode == "llm" else f"fixed plan{(' (' + plan.reason + ')') if plan.reason else ''}"
    return card(
        "Plan for this run",
        fields=[("Goal", cell(plan.goal, 160)), ("Focus", plan.focus or "all sectors"),
                ("Start with", ", ".join(plan.prefer) if plan.prefer else "decided by the discovery agent"), ("How decided", how)],
        note=plan.notes or None,
    )


def assessment_card(run_id: str, assessment: dict, modes: dict) -> str:
    ran = [f"{k}: {'model' if v == 'llm' else 'fixed policy'}" for k, v in modes.items()]
    return card(
        f"Run {code(run_id[:8])} · assessment",
        lead=assessment["assessment"],
        fields=[("Suggestion", assessment.get("next_suggestion")), ("Who decided", " · ".join(ran) if ran else None)],
        note=("Commentary written by the model. The counts above are from the database." if assessment.get("mode") == "llm" else None),
    )
