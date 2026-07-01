"""Bandit detector (security).

Runs Bandit as a subprocess (``-f json``) against a file on disk and converts
each result into a :class:`RawFinding`. Bandit covers the security half of the
symbolic layer: hardcoded passwords, ``eval``/``exec``, unsafe subprocess,
weak crypto, shell/SQL injection patterns, etc.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.schemas.issue import RawFinding, ToolSource
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# Map Bandit test ids to readable issue types. Unknown ids fall back to the
# (already readable) test name.
_TESTID_TO_TYPE: dict[str, str] = {
    "B105": "Hardcoded Password",
    "B106": "Hardcoded Password",
    "B107": "Hardcoded Password",
    "B102": "Use of exec()",
    "B307": "Use of eval()",
    "B602": "Shell Injection",
    "B603": "Unsafe subprocess()",
    "B604": "Shell Injection",
    "B605": "Shell Injection",
    "B608": "SQL Injection",
    "B303": "Weak Cryptography",
    "B304": "Weak Cryptography",
    "B305": "Weak Cryptography",
    "B324": "Weak Cryptography",
    "B501": "Insecure SSL/TLS",
}


def _testid_to_type(test_id: str, test_name: str) -> str:
    return _TESTID_TO_TYPE.get(test_id, test_name.replace("_", " ").title())


def run_bandit(file_path: Path) -> list[RawFinding]:
    """Run Bandit on ``file_path`` and return raw findings.

    Like the Pylint runner, failures degrade gracefully to an empty list.
    """
    cmd = [sys.executable, "-m", "bandit", "-f", "json", "-q", str(file_path)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Bandit failed to run on %s: %s", file_path, exc)
        return []

    if not proc.stdout.strip():
        return []

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("Bandit produced non-JSON output for %s", file_path)
        return []

    findings: list[RawFinding] = []
    for result in payload.get("results", []):
        test_id = result.get("test_id", "")
        test_name = result.get("test_name", "")
        findings.append(
            RawFinding(
                tool=ToolSource.BANDIT,
                code=test_id,
                message=result.get("issue_text", ""),
                line=result.get("line_number", 0) or 0,
                column=result.get("col_offset"),
                raw_severity=result.get("issue_severity"),  # LOW/MEDIUM/HIGH
                extra={
                    "type": _testid_to_type(test_id, test_name),
                    "confidence": result.get("issue_confidence"),
                    "cwe": (result.get("issue_cwe") or {}).get("id"),
                },
            )
        )
    return findings
