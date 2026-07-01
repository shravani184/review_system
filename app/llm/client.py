"""LLM reasoning client.

Defines the :class:`Explainer` interface and two implementations:

* :class:`OpenAIExplainer` — calls the OpenAI chat completions API to explain
  verified findings.
* :class:`OfflineExplainer` — a deterministic, template-driven explainer used
  when no API key is configured (or as a fallback when the API call fails).

Both honour the neuro-symbolic contract: they explain the findings they are
given and never introduce new ones. The :func:`get_explainer` factory performs
the dependency-injection selection based on :class:`app.config.Settings`.

The return type is :class:`Explanation` per finding index, carrying an
``agreement`` signal consumed by the confidence engine.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.llm import prompt as prompt_mod
from app.schemas.issue import NormalizedFinding
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class Explanation:
    """LLM/offline output for a single finding."""

    explanation: str
    suggestion: str
    agreement: float  # 0..1; how strongly the explainer confirms the finding


class Explainer(ABC):
    """Interface for explanation backends."""

    mode: str = "offline"

    @abstractmethod
    def explain(self, source: str,
                findings: list[NormalizedFinding]) -> dict[int, Explanation]:
        """Return an :class:`Explanation` per finding index."""


# --------------------------------------------------------------------------- #
# Offline template knowledge base
# --------------------------------------------------------------------------- #
# Grounded, non-hallucinated explanations keyed by normalized issue type. These
# describe *why the rule fires* and a generic remediation — they never claim a
# bug the symbolic layer did not report.
_TEMPLATES: dict[str, tuple[str, str]] = {
    "Hardcoded Password": (
        "A credential appears to be embedded directly in the source code, "
        "which exposes it to anyone with repository access.",
        "Move the secret into an environment variable or a secrets manager and "
        "read it at runtime (e.g. os.environ['DB_PASSWORD']).",
    ),
    "Undefined Variable": (
        "This name is used before it is assigned or imported in the current "
        "scope, so it will raise a NameError at runtime.",
        "Define, import, or pass the variable before it is referenced.",
    ),
    "Unused Import": (
        "This module is imported but never referenced, adding noise and a "
        "small import-time cost.",
        "Remove the unused import.",
    ),
    "Unused Variable": (
        "This variable is assigned but never read, which often signals dead "
        "code or a typo.",
        "Remove the assignment or use the value; prefix with '_' if "
        "intentionally unused.",
    ),
    "Use of eval()": (
        "eval() executes arbitrary input as code and is a common remote-code-"
        "execution vector.",
        "Replace eval() with ast.literal_eval() for data, or explicit parsing "
        "logic.",
    ),
    "Use of exec()": (
        "exec() runs arbitrary code and can execute attacker-controlled input.",
        "Avoid exec(); use explicit, validated logic instead.",
    ),
    "Shell Injection": (
        "Building a shell command from untrusted input allows command "
        "injection.",
        "Use subprocess with a list of arguments and shell=False; never "
        "interpolate user input into a shell string.",
    ),
    "SQL Injection": (
        "Constructing SQL by string interpolation allows SQL injection.",
        "Use parameterized queries / prepared statements with bound "
        "parameters.",
    ),
    "Unsafe subprocess()": (
        "A subprocess call uses patterns that can execute unintended commands.",
        "Pass arguments as a list and set shell=False; validate any dynamic "
        "input.",
    ),
    "Weak Cryptography": (
        "A weak or broken cryptographic primitive (e.g. MD5/SHA1/DES) is used.",
        "Use a modern algorithm such as SHA-256+ for hashing or AES-GCM for "
        "encryption.",
    ),
    "Missing Docstring": (
        "This module, class, or function lacks a docstring, reducing "
        "readability and tooling support.",
        "Add a short docstring describing purpose, parameters, and return "
        "value.",
    ),
    "Naming Convention Violation": (
        "This identifier does not follow the project's naming conventions.",
        "Rename to match the expected style (snake_case for functions/"
        "variables, UPPER_CASE for constants, PascalCase for classes).",
    ),
    "Long Function": (
        "This function is long enough that it is hard to read and test as a "
        "single unit.",
        "Extract cohesive blocks into smaller, well-named helper functions.",
    ),
    "Too Many Arguments": (
        "This function takes many parameters, which complicates calling and "
        "testing.",
        "Group related parameters into a dataclass or pass a configuration "
        "object.",
    ),
    "Nested Loops": (
        "Nested loops increase complexity and can hide performance problems.",
        "Refactor into helper functions, use comprehensions, or vectorize the "
        "inner computation.",
    ),
    "Deep Nesting": (
        "Deeply nested control flow is hard to follow and error-prone.",
        "Flatten with early returns / guard clauses or extract helpers.",
    ),
    "Cyclomatic Complexity": (
        "High cyclomatic complexity means many independent paths, making the "
        "function hard to test thoroughly.",
        "Break the function into smaller pieces and reduce branching.",
    ),
    "Dead Code": (
        "This code can never execute or has no effect.",
        "Remove the unreachable or no-op code.",
    ),
    "Magic Number": (
        "An unexplained numeric literal makes the code harder to understand "
        "and maintain.",
        "Replace it with a named constant that documents its meaning.",
    ),
    "Duplicate Imports": (
        "The same name is imported more than once.",
        "Keep a single import and remove the duplicates.",
    ),
    "Missing Type Hints": (
        "Missing type annotations reduce IDE support and static checking.",
        "Add type hints to parameters and the return value.",
    ),
    "Line Too Long": (
        "This line exceeds the configured maximum length, hurting "
        "readability.",
        "Wrap the line or refactor to keep it within the limit.",
    ),
}

_GENERIC = (
    "A static-analysis tool flagged this location based on a deterministic "
    "rule.",
    "Review the reported message and adjust the code to satisfy the rule.",
)


class OfflineExplainer(Explainer):
    """Deterministic explainer using the template knowledge base."""

    mode = "offline"

    def explain(self, source: str,
                findings: list[NormalizedFinding]) -> dict[int, Explanation]:
        out: dict[int, Explanation] = {}
        for i, f in enumerate(findings):
            explanation, suggestion = _TEMPLATES.get(f.type, _GENERIC)
            out[i] = Explanation(
                explanation=explanation,
                suggestion=suggestion,
                # Offline mode does not second-guess the symbolic layer; it
                # agrees fully but contributes no independent signal, so we use
                # a neutral-high agreement.
                agreement=0.85,
            )
        return out


class OpenAIExplainer(Explainer):
    """Explainer backed by the OpenAI chat completions API."""

    mode = "openai"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fallback = OfflineExplainer()

    def _call_api(self, source: str,
                  findings: list[NormalizedFinding]) -> dict[int, dict]:
        # Imported lazily so the package works without the dependency installed
        # when running purely in offline mode.
        import httpx  # noqa: WPS433

        s = self._settings
        body = {
            "model": s.openai_model,
            "temperature": s.openai_temperature,
            "max_tokens": s.openai_max_tokens,
            "response_format": {"type": "json_object"},
            "messages": prompt_mod.build_messages(source, findings),
        }
        headers = {"Authorization": f"Bearer {s.openai_api_key}"}
        resp = httpx.post(
            f"{s.openai_base_url}/chat/completions",
            json=body, headers=headers, timeout=s.openai_timeout_seconds,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return prompt_mod.parse_llm_json(content)

    def explain(self, source: str,
                findings: list[NormalizedFinding]) -> dict[int, Explanation]:
        if not findings:
            return {}
        try:
            parsed = self._call_api(source, findings)
        except Exception as exc:  # network/auth/parse — degrade gracefully
            logger.warning("OpenAI call failed (%s); using offline explainer.",
                           exc)
            return self._fallback.explain(source, findings)

        if not parsed:
            return self._fallback.explain(source, findings)

        offline = self._fallback.explain(source, findings)
        out: dict[int, Explanation] = {}
        for i, _f in enumerate(findings):
            item = parsed.get(i)
            if not item:
                out[i] = offline[i]  # fill any gaps deterministically
                continue
            confirmed = bool(item.get("confirmed", True))
            out[i] = Explanation(
                explanation=item.get("explanation") or offline[i].explanation,
                suggestion=item.get("suggestion") or offline[i].suggestion,
                # A confirmed finding gets high agreement; an unconfirmed one
                # gets low agreement, which the confidence engine penalizes.
                agreement=0.95 if confirmed else 0.2,
            )
        return out


def get_explainer(settings: Settings | None = None) -> Explainer:
    """Factory: select the explainer implementation (dependency injection)."""
    settings = settings or get_settings()
    if settings.use_real_llm:
        logger.info("Using OpenAIExplainer (model=%s).", settings.openai_model)
        return OpenAIExplainer(settings)
    logger.info("Using OfflineExplainer (no API key / LLM disabled).")
    return OfflineExplainer()
