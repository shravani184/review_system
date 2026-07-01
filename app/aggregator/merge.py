"""Output aggregation layer.

Fuses normalized findings with their LLM/offline explanations into final
:class:`Issue` objects, deduplicates near-identical findings reported by more
than one tool, computes confidence, and produces a deterministic ordering.
"""
from __future__ import annotations

from app.aggregator.confidence import compute_confidence
from app.config import ConfidenceWeights
from app.llm.client import Explanation
from app.schemas.issue import Issue, NormalizedFinding


def _dedupe_key(f: NormalizedFinding) -> tuple[int, str]:
    """Two findings collide if they target the same line and issue type."""
    return (f.line, f.type)


def merge(
    findings: list[NormalizedFinding],
    explanations: dict[int, Explanation],
    weights: ConfidenceWeights | None = None,
) -> list[Issue]:
    """Combine findings + explanations into sorted, de-duplicated issues.

    ``explanations`` is keyed by the index of ``findings`` (as produced by the
    explainer). When the same (line, type) is reported by multiple tools, the
    higher-confidence instance wins.
    """
    issues: dict[tuple[int, str], Issue] = {}

    for i, finding in enumerate(findings):
        exp = explanations.get(i)
        explanation = exp.explanation if exp else finding.message
        suggestion = exp.suggestion if exp else "Review and address the finding."
        agreement = exp.agreement if exp else 0.85

        confidence = compute_confidence(finding, agreement, weights)

        issue = Issue(
            tool=finding.tool,
            type=finding.type,
            severity=finding.severity,
            line=finding.line,
            column=finding.column,
            filename=finding.filename,
            code=finding.code,
            message=finding.message,
            explanation=explanation,
            suggestion=suggestion,
            confidence=confidence,
        )

        key = _dedupe_key(finding)
        existing = issues.get(key)
        if existing is None or issue.confidence > existing.confidence:
            issues[key] = issue

    # Deterministic ordering: severity (high -> low), then line, then type.
    return sorted(
        issues.values(),
        key=lambda x: (-x.severity.rank, x.line, x.type),
    )
