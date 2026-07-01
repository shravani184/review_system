"""Confidence engine.

Implements::

    Confidence = w_tool * static_tool_score
               + w_llm  * llm_agreement
               + w_rule * rule_reliability

with weights from :class:`app.config.ConfidenceWeights`. Each component is in
``[0, 1]`` and the final score is clamped to ``[0, 1]``.

Components
----------
* **static_tool_score** — the detecting tool's per-finding reliability, lifted
  by a small severity bonus (high-severity findings are typically more certain
  and more important to surface confidently).
* **llm_agreement** — how strongly the explanation backend confirmed the
  finding (offline mode contributes a neutral-high constant; a real LLM that
  *disconfirms* a finding pushes this toward 0).
* **rule_reliability** — a baseline trust level for the source detector.
"""
from __future__ import annotations

from app.config import ConfidenceWeights, get_settings
from app.schemas.issue import NormalizedFinding, Severity, ToolSource

# Per-tool baseline reliability for the rule-reliability component.
_RULE_BASELINE: dict[ToolSource, float] = {
    ToolSource.PYLINT: 0.90,
    ToolSource.BANDIT: 0.90,
    ToolSource.CUSTOM: 0.80,
}

# Severity bonus added to the static tool score (then clamped to 1.0).
_SEVERITY_BONUS: dict[Severity, float] = {
    Severity.INFO: 0.0,
    Severity.LOW: 0.0,
    Severity.MEDIUM: 0.05,
    Severity.HIGH: 0.10,
    Severity.CRITICAL: 0.15,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def static_tool_score(finding: NormalizedFinding) -> float:
    """Reliability of the detecting tool for this finding, severity-adjusted."""
    return _clamp(finding.tool_reliability + _SEVERITY_BONUS[finding.severity])


def rule_reliability(finding: NormalizedFinding) -> float:
    """Baseline trust level for the source detector."""
    return _RULE_BASELINE[finding.tool]


def compute_confidence(
    finding: NormalizedFinding,
    llm_agreement: float,
    weights: ConfidenceWeights | None = None,
) -> float:
    """Compute the blended confidence score for one finding."""
    w = weights or get_settings().confidence
    score = (
        w.static_tool_weight * static_tool_score(finding)
        + w.llm_agreement_weight * _clamp(llm_agreement)
        + w.rule_reliability_weight * rule_reliability(finding)
    )
    return round(_clamp(score), 4)
