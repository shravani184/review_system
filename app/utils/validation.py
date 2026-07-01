"""Input validation utilities.

Responsible for the *gatekeeping* step of the pipeline: only well-formed,
parseable Python source proceeds to analysis. Invalid input is rejected with a
clear reason rather than crashing a downstream tool.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass


class ValidationError(Exception):
    """Raised when an uploaded file fails validation."""


@dataclass(frozen=True)
class SyntaxCheckResult:
    """Outcome of a syntax pre-check."""

    valid: bool
    line: int | None = None
    message: str | None = None


def validate_filename(filename: str | None) -> str:
    """Validate and return a safe filename.

    Rejects path-traversal attempts and non-``.py`` files.
    """
    if not filename:
        raise ValidationError("Missing filename.")
    # Reject directory components to prevent path traversal.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValidationError(f"Unsafe filename: {filename!r}")
    if not filename.endswith(".py"):
        raise ValidationError(f"Only Python (.py) files are supported: {filename!r}")
    return filename


def validate_size(content: bytes, max_bytes: int) -> None:
    """Reject empty or oversized payloads."""
    if not content:
        raise ValidationError("File is empty.")
    if len(content) > max_bytes:
        raise ValidationError(
            f"File too large: {len(content)} bytes (limit {max_bytes})."
        )


def check_syntax(source: str) -> SyntaxCheckResult:
    """Compile-check Python source without executing it.

    Uses :func:`ast.parse`, which never runs user code — safe for untrusted
    input. Returns a structured result instead of raising so the API can report
    the offending line.
    """
    try:
        ast.parse(source)
        return SyntaxCheckResult(valid=True)
    except SyntaxError as exc:  # includes IndentationError
        return SyntaxCheckResult(
            valid=False,
            line=exc.lineno,
            message=f"{exc.msg} (line {exc.lineno})",
        )
