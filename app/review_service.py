"""Review service — the orchestration / use-case layer.

Coordinates the full pipeline for a single file and for a batch, keeping the
FastAPI handlers thin and the pipeline independently testable. Dependencies
(the explainer, the rule engine) are injected so tests can substitute fakes.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analyzers.bandit_runner import run_bandit
from app.analyzers.custom_rules import RuleEngine
from app.analyzers.pylint_runner import run_pylint
from app.aggregator.merge import merge
from app.config import Settings, get_settings
from app.llm.client import Explainer, get_explainer
from app.normalizer.normalize import normalize_all
from app.parser.ast_parser import parse_module
from app.schemas.issue import FileReview, RawFinding
from app.utils.file_utils import Workspace
from app.utils.logging_config import get_logger
from app.utils.validation import (
    ValidationError,
    check_syntax,
    validate_filename,
    validate_size,
)

logger = get_logger(__name__)


@dataclass
class SourceFile:
    """An in-memory uploaded file."""

    filename: str
    content: bytes


class ReviewService:
    """Runs the neuro-symbolic review pipeline."""

    def __init__(
        self,
        settings: Settings | None = None,
        explainer: Explainer | None = None,
        rule_engine: RuleEngine | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._explainer = explainer or get_explainer(self._settings)
        self._rules = rule_engine or RuleEngine()

    @property
    def llm_mode(self) -> str:
        return self._explainer.mode

    # ---- single file -----------------------------------------------------
    def review_file(self, file: SourceFile) -> FileReview:
        """Run the pipeline for one file, returning a :class:`FileReview`."""
        # 1. Validate filename + size (gatekeeping).
        try:
            filename = validate_filename(file.filename)
            validate_size(file.content, self._settings.max_file_bytes)
            source = file.content.decode("utf-8")
        except (ValidationError, UnicodeDecodeError) as exc:
            return FileReview(
                filename=file.filename or "<unknown>",
                syntax_valid=False,
                error=str(exc),
            )

        # 2. Syntax pre-check — reject invalid Python before any tool runs.
        syntax = check_syntax(source)
        if not syntax.valid:
            return FileReview(
                filename=filename,
                syntax_valid=False,
                error=f"Syntax error: {syntax.message}",
            )

        # 3. AST metadata extraction (no detection).
        metadata = parse_module(source)

        # 4. Symbolic analysis = source of truth. Tools need a file on disk.
        raw: list[RawFinding] = []
        with Workspace(self._settings.workspace_root) as ws:
            path = ws.write(filename, source)
            raw.extend(run_pylint(path))
            raw.extend(run_bandit(path))
        raw.extend(self._rules.run(source, metadata, self._settings.rules))

        # 5. Normalize into the common schema.
        normalized = normalize_all(raw, filename=filename)

        # 6. LLM reasoning — explain ONLY verified findings.
        explanations = self._explainer.explain(source, normalized)

        # 7. Confidence + aggregation.
        issues = merge(normalized, explanations, self._settings.confidence)

        logger.info("Reviewed %s: %d issue(s).", filename, len(issues))
        return FileReview(
            filename=filename,
            syntax_valid=True,
            issues=issues,
            issue_count=len(issues),
        )

    # ---- batch -----------------------------------------------------------
    def review_files(self, files: list[SourceFile]) -> list[FileReview]:
        """Review multiple files independently."""
        return [self.review_file(f) for f in files]
