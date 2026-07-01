"""Convenience entry point: ``python run.py`` starts the dev server.

In production prefer running uvicorn/gunicorn directly, e.g.::

    uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 4
"""
from __future__ import annotations

import uvicorn

from app.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )
