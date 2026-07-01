"""Unit tests for the normalizer and confidence engine."""
from app.aggregator.confidence import compute_confidence
from app.config import ConfidenceWeights
from app.normalizer.normalize import normalize
from app.schemas.issue import RawFinding, Severity, ToolSource


def test_normalize_security_floor():
    """A Bandit LOW hardcoded-password is floored to at least High."""
    raw = RawFinding(
        tool=ToolSource.BANDIT,
        code="B105",
        message="Possible hardcoded password",
        line=1,
        raw_severity="LOW",
        extra={"type": "Hardcoded Password"},
    )
    norm = normalize(raw, filename="x.py")
    assert norm.type == "Hardcoded Password"
    assert norm.severity in (Severity.HIGH, Severity.CRITICAL)
    assert norm.severity.rank >= Severity.HIGH.rank


def test_normalize_pylint_convention_is_low():
    raw = RawFinding(
        tool=ToolSource.PYLINT,
        code="C0114",
        message="Missing module docstring",
        line=1,
        raw_severity="convention",
        extra={"type": "Missing Docstring"},
    )
    norm = normalize(raw)
    assert norm.severity == Severity.LOW


def test_confidence_formula_matches_weights():
    weights = ConfidenceWeights(
        static_tool_weight=0.5,
        llm_agreement_weight=0.3,
        rule_reliability_weight=0.2,
    )
    raw = RawFinding(
        tool=ToolSource.BANDIT, code="B105", message="m", line=1,
        raw_severity="LOW", extra={"type": "Hardcoded Password"},
    )
    norm = normalize(raw)
    score = compute_confidence(norm, llm_agreement=0.95, weights=weights)
    # Bounded and high for a high-severity, high-reliability security finding.
    assert 0.0 <= score <= 1.0
    assert score > 0.85


def test_confidence_clamped_to_unit_interval():
    raw = RawFinding(
        tool=ToolSource.CUSTOM, code="CR001", message="m", line=1,
        raw_severity="warning", extra={"type": "Long Function"},
    )
    norm = normalize(raw)
    high = compute_confidence(norm, llm_agreement=1.0)
    low = compute_confidence(norm, llm_agreement=0.0)
    assert 0.0 <= low <= high <= 1.0
