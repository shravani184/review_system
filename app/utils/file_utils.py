"""Temporary workspace management.

Pylint and Bandit operate on files on disk, so each request gets an isolated
temp directory. The :class:`Workspace` context manager guarantees cleanup even
when analysis raises.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from types import TracebackType


class Workspace:
    """An isolated, auto-cleaned temporary directory for one review request.

    Usage::

        with Workspace(root="/tmp/review_workspaces") as ws:
            path = ws.write("foo.py", source_code)
            ...  # run analyzers against `path`
    """

    def __init__(self, root: str | None = None) -> None:
        if root:
            os.makedirs(root, exist_ok=True)
        self._root = root
        self.path: Path | None = None

    def __enter__(self) -> "Workspace":
        self.path = Path(tempfile.mkdtemp(prefix="review_", dir=self._root))
        return self

    def write(self, filename: str, source: str) -> Path:
        """Write ``source`` to ``filename`` inside the workspace; return path."""
        if self.path is None:  # pragma: no cover - misuse guard
            raise RuntimeError("Workspace not entered.")
        target = self.path / filename
        target.write_text(source, encoding="utf-8")
        return target

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.path and self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        self.path = None
