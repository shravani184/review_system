"""Normalization layer.

Collapses heterogeneous detector output (:class:`RawFinding`) into a single
:class:`NormalizedFinding` shape with a unified :class:`Severity` and a
per-finding ``tool_reliability`` score for the confidence engine.

Two override tables encode domain knowledge:

* ``_TYPE_SEVERITY_FLOOR`` raises severity for high-signal issue types
  (e.g. a hardcoded password is always at least High, regardless of Bandit's
  native LOW rating).
* ``_RELIABILITY`` rates how trustworthy each (tool, type) pairing is.
"""
from __future__ import annotations

from app.schemas.issue import NormalizedFinding, RawFinding, Severity, ToolSource

# --- Native severity strings -> normalized Severity ---------------------------
_PYLINT_SEVERITY = {
    "fatal": Severity.CRITICAL,
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "refactor": Severity.LOW,
    "convention": Severity.LOW,
    "info": Severity.INFO,
}
_BANDIT_SEVERITY = {
    "HIGH": Severity.CRITICAL,
    "MEDIUM": Severity.HIGH,
    "LOW": Severity.MEDIUM,
}
_CUSTOM_SEVERITY = {
    "error": Severity.HIGH,
    "warning": Severity.MEDIUM,
    "convention": Severity.LOW,
    "info": Severity.INFO,
}

# --- Severity floor by issue type (security & correctness get boosted) --------
_TYPE_SEVERITY_FLOOR: dict[str, Severity] = {
    "Hardcoded Password": Severity.HIGH,
    "Use of eval()": Severity.HIGH,
    "Use of exec()": Severity.HIGH,
    "Shell Injection": Severity.CRITICAL,
    "SQL Injection": Severity.HIGH,
    "Unsafe subprocess()": Severity.HIGH,
    "Weak Cryptography": Severity.HIGH,
    "Undefined Variable": Severity.HIGH,
    "Syntax Error": Severity.CRITICAL,
}

# --- Static reliability of (tool, type) for the confidence engine -------------
_RELIABILITY: dict[tuple[ToolSource, str], float] = {
    (ToolSource.BANDIT, "Hardcoded Password"): 0.9,
    (ToolSource.BANDIT, "Use of eval()"): 0.95,
    (ToolSource.BANDIT, "Use of exec()"): 0.95,
    (ToolSource.BANDIT, "Shell Injection"): 0.9,
    (ToolSource.BANDIT, "SQL Injection"): 0.75,
    (ToolSource.PYLINT, "Undefined Variable"): 0.95,
    (ToolSource.PYLINT, "Unused Import"): 0.9,
    (ToolSource.PYLINT, "Unused Variable"): 0.85,
    (ToolSource.PYLINT, "Duplicate Imports"): 0.9,
}
_DEFAULT_RELIABILITY = {
    ToolSource.PYLINT: 0.8,
    ToolSource.BANDIT: 0.85,
    ToolSource.CUSTOM: 0.75,
}


def _normalize_severity(raw: RawFinding) -> Severity:
    native = (raw.raw_severity or "").strip()
    if raw.tool is ToolSource.PYLINT:
        base = _PYLINT_SEVERITY.get(native.lower(), Severity.MEDIUM)
    elif raw.tool is ToolSource.BANDIT:
        base = _BANDIT_SEVERITY.get(native.upper(), Severity.MEDIUM)
    else:
        base = _CUSTOM_SEVERITY.get(native.lower(), Severity.LOW)

    issue_type = raw.extra.get("type", "")
    floor = _TYPE_SEVERITY_FLOOR.get(issue_type)
    if floor and floor.rank > base.rank:
        return floor
    return base


def _reliability(tool: ToolSource, issue_type: str) -> float:
    return _RELIABILITY.get((tool, issue_type), _DEFAULT_RELIABILITY[tool])


def normalize(raw: RawFinding, filename: str | None = None) -> NormalizedFinding:
    """Convert a single :class:`RawFinding` into a :class:`NormalizedFinding`."""
    issue_type = raw.extra.get("type") or raw.message[:40] or "Issue"
    severity = _normalize_severity(raw)
    return NormalizedFinding(
        tool=raw.tool,
        type=issue_type,
        severity=severity,
        line=raw.line,
        column=raw.column,
        message=raw.message,
        code=raw.code,
        filename=filename,
        tool_reliability=_reliability(raw.tool, issue_type),
    )


def normalize_all(raws: list[RawFinding],
                  filename: str | None = None) -> list[NormalizedFinding]:
    """Normalize a batch of raw findings."""
    return [normalize(r, filename) for r in raws]
