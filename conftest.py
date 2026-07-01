"""Pytest bootstrap: force deterministic offline mode for the whole suite."""
import os

os.environ.setdefault("LLM_ENABLED", "false")
os.environ.pop("OPENAI_API_KEY", None)
