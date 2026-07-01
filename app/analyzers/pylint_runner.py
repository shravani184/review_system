"""Pylint detector.

Runs Pylint as a subprocess (``--output-format=json``) against a file on disk
and converts each message into a :class:`RawFinding`. Subprocess isolation
keeps Pylint's global state out of our process and survives its occasional
hard exits.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.schemas.issue import RawFinding, ToolSource
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# Pylint symbol -> human-readable issue type used in our common schema.
# Anything not listed falls back to the title-cased symbol.
_SYMBOL_TO_TYPE: dict[str, str] = {
    "undefined-variable": "Undefined Variable",
    "unused-variable": "Unused Variable",
    "unused-import": "Unused Import",
    "missing-module-docstring": "Missing Docstring",
    "missing-class-docstring": "Missing Docstring",
    "missing-function-docstring": "Missing Docstring",
    "invalid-name": "Naming Convention Violation",
    "too-many-arguments": "Too Many Arguments",
    "too-many-locals": "Too Many Locals",
    "too-many-branches": "High Complexity",
    "too-many-statements": "Long Function",
    "multiple-imports": "Duplicate Imports",
    "reimported": "Duplicate Imports",
    "unreachable": "Dead Code",
    "pointless-statement": "Dead Code",
    "syntax-error": "Syntax Error",
    # Align with Bandit naming so overlapping findings deduplicate cleanly.
    "eval-used": "Use of eval()",
    "exec-used": "Use of exec()",
}


def _symbol_to_type(symbol: str) -> str:
    return _SYMBOL_TO_TYPE.get(symbol, symbol.replace("-", " ").title())


def run_pylint(file_path: Path) -> list[RawFinding]:
    """Run Pylint on ``file_path`` and return raw findings.

    Never raises on analysis failure: a broken Pylint run yields an empty list
    plus a logged warning, so one detector failing cannot fail the request.
    """
    cmd = [
        sys.executable, "-m", "pylint",
        "--output-format=json",
        "--score=n",
        str(file_path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Pylint failed to run on %s: %s", file_path, exc)
        return []

    if not proc.stdout.strip():
        return []

    try:
        messages = json.loads(proc.stdout)
    except json.JSONDecodeError:
        logger.warning("Pylint produced non-JSON output for %s", file_path)
        return []

    findings: list[RawFinding] = []
    for msg in messages:
        symbol = msg.get("symbol", "")
        findings.append(
            RawFinding(
                tool=ToolSource.PYLINT,
                code=msg.get("message-id"),
                message=msg.get("message", ""),
                line=msg.get("line", 0) or 0,
                column=msg.get("column"),
                raw_severity=msg.get("type"),  # convention/warning/error/...
                extra={"symbol": symbol, "type": _symbol_to_type(symbol)},
            )
        )
    return findings
