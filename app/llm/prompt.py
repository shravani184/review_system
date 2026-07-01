"""Prompt construction for the LLM reasoning layer.

The prompt enforces the neuro-symbolic contract: the model receives a *closed,
numbered list* of verified findings and is told to explain each by index. It
is explicitly forbidden from detecting new issues. Output is requested as
strict JSON keyed by finding index so the merge layer can re-attach
explanations to the exact symbolic findings they belong to.
"""
from __future__ import annotations

import json

from app.schemas.issue import NormalizedFinding

SYSTEM_PROMPT = (
    "You are a senior software engineer assisting with code review. "
    "You are given source code and a list of VERIFIED issues that were already "
    "detected by deterministic static-analysis tools (Pylint, Bandit, and a "
    "custom AST rule engine). "
    "Your job is strictly limited to the following:\n"
    "  1. Explain ONLY the supplied, numbered issues.\n"
    "  2. Suggest a concrete fix for each supplied issue.\n"
    "  3. Do NOT detect, infer, or invent any new issues.\n"
    "  4. Do NOT comment on anything not in the supplied list.\n"
    "If a supplied issue does not actually appear valid given the code, set "
    '"confirmed" to false for that issue and explain why briefly.\n'
    "Respond with STRICT JSON only — no markdown, no prose outside the JSON."
)

# Shape requested from the model. Keyed by the integer index of each finding.
_OUTPUT_SPEC = (
    "Return a JSON object of the form:\n"
    "{\n"
    '  "items": [\n'
    '    {"index": <int>, "confirmed": <bool>, '
    '"explanation": "<concise developer-friendly explanation>", '
    '"suggestion": "<concrete fix>"}\n'
    "  ]\n"
    "}\n"
    "Include exactly one object per supplied issue, matching its index."
)


def build_findings_block(findings: list[NormalizedFinding]) -> str:
    """Render the verified findings as a stable, numbered block."""
    lines = []
    for i, f in enumerate(findings):
        lines.append(
            f"[{i}] line {f.line} | {f.severity.value} | {f.type} "
            f"| tool={f.tool.value} | message: {f.message}"
        )
    return "\n".join(lines)


def build_user_prompt(source: str, findings: list[NormalizedFinding]) -> str:
    """Assemble the full user message for the explain-only task."""
    return (
        "SOURCE CODE:\n"
        "```python\n"
        f"{source}\n"
        "```\n\n"
        "VERIFIED ISSUES (explain ONLY these, do not add new ones):\n"
        f"{build_findings_block(findings)}\n\n"
        f"{_OUTPUT_SPEC}"
    )


def build_messages(source: str,
                   findings: list[NormalizedFinding]) -> list[dict[str, str]]:
    """Build the chat ``messages`` payload for the OpenAI client."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(source, findings)},
    ]


def parse_llm_json(content: str) -> dict[int, dict]:
    """Parse the model's JSON reply into ``{index: {confirmed,...}}``.

    Tolerant of stray markdown fences. Returns an empty dict on failure so the
    caller can fall back to offline explanations.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        # drop a leading "json" language tag if present
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    result: dict[int, dict] = {}
    for item in payload.get("items", []):
        try:
            result[int(item["index"])] = item
        except (KeyError, ValueError, TypeError):
            continue
    return result
