"""FastAPI application — the API layer.

Exposes:

* ``POST /review``  — accept one or more ``.py`` files (multipart) and return a
  strict-JSON :class:`ReviewResponse`.
* ``GET  /health``  — service + analyzer health.
* ``GET  /``        — basic service metadata.

The :class:`ReviewService` is supplied via dependency injection so tests (and
alternative deployments) can substitute their own implementation.
"""
from __future__ import annotations

import shutil
import sys

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.review_service import ReviewService, SourceFile
from app.schemas.issue import HealthResponse, ReviewResponse
from app.utils.logging_config import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Neuro-symbolic code review: deterministic static analysis detects "
        "issues; the LLM only explains verified findings."
    ),
)

# Single shared service instance (stateless; safe to reuse across requests).
_service = ReviewService(settings)


def get_service() -> ReviewService:
    """DI provider for the review service (override in tests)."""
    return _service


def _analyzer_available(module: str) -> bool:
    """Whether an analyzer CLI module is importable in this environment."""
    try:
        __import__(module)
        return True
    except ImportError:
        return False


@app.get("/", tags=["meta"])
def root(cfg: Settings = Depends(get_settings)) -> dict:
    """Basic service metadata."""
    return {
        "service": cfg.app_name,
        "version": cfg.app_version,
        "endpoints": ["POST /review", "GET /health"],
    }


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health(
    cfg: Settings = Depends(get_settings),
    service: ReviewService = Depends(get_service),
) -> HealthResponse:
    """Report service status and analyzer availability."""
    return HealthResponse(
        status="ok",
        app=cfg.app_name,
        version=cfg.app_version,
        llm_mode=service.llm_mode,
        analyzers={
            "pylint": _analyzer_available("pylint"),
            "bandit": _analyzer_available("bandit"),
            "custom_rules": True,
        },
    )


@app.post("/review", response_model=ReviewResponse, tags=["review"])
async def review(
    files: list[UploadFile],
    cfg: Settings = Depends(get_settings),
    service: ReviewService = Depends(get_service),
) -> ReviewResponse:
    """Review one or more uploaded Python files.

    Accepts a multipart request with one or many ``files`` parts. Invalid or
    non-Python files are reported per-file rather than failing the whole batch.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")
    if len(files) > cfg.max_files_per_request:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (limit {cfg.max_files_per_request}).",
        )

    sources: list[SourceFile] = []
    for upload in files:
        content = await upload.read()
        sources.append(SourceFile(filename=upload.filename or "", content=content))

    reviews = service.review_files(sources)
    total = sum(r.issue_count for r in reviews)

    return ReviewResponse(
        status="ok",
        files=reviews,
        total_issues=total,
        llm_mode=service.llm_mode,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):  # pragma: no cover
    """Last-resort handler so internal errors return clean JSON, not HTML."""
    logger.exception("Unhandled error processing %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "Internal server error."},
    )
