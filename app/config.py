"""Application configuration.

All tunable behaviour (custom-rule thresholds, confidence weights, LLM
provider selection) is centralized here and overridable via environment
variables or a ``.env`` file. No magic numbers should live deeper in the
stack — modules read them from :data:`settings`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CustomRuleConfig(BaseSettings):
    """Thresholds for the custom AST rule engine.

    Each value is a single, well-named knob. Raising/lowering a threshold
    changes rule behaviour without touching rule code.
    """

    model_config = SettingsConfigDict(env_prefix="RULE_")

    max_function_length: int = 50          # logical lines in a function body
    max_parameters: int = 5                # positional/keyword params
    max_nesting_depth: int = 4             # nested compound statements
    max_cyclomatic_complexity: int = 10    # McCabe complexity
    max_line_length: int = 100             # characters per physical line
    enforce_type_hints: bool = True        # flag missing param/return hints
    enforce_docstrings: bool = True        # flag missing module/func/class docs
    flag_magic_numbers: bool = True        # flag unexplained numeric literals
    flag_nested_loops: bool = True         # flag loop-inside-loop


class ConfidenceWeights(BaseSettings):
    """Weights for the confidence engine.

    ``Confidence = w_tool*tool + w_llm*llm_agreement + w_rule*rule_reliability``
    The three weights are expected to sum to 1.0 (validated at load time).
    """

    model_config = SettingsConfigDict(env_prefix="CONF_")

    static_tool_weight: float = 0.5
    llm_agreement_weight: float = 0.3
    rule_reliability_weight: float = 0.2


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Service ---
    app_name: str = "Hybrid LLM Code Review System"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    workspace_root: str = "/tmp/review_workspaces"

    # --- LLM provider ---
    # When no API key is supplied (or llm_enabled is False) the system falls
    # back to a deterministic offline explainer. The neuro-symbolic contract
    # holds either way: the explainer never invents issues.
    llm_enabled: bool = True
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout_seconds: float = 30.0
    openai_max_tokens: int = 1500
    openai_temperature: float = 0.0  # deterministic; we want grounded output

    # --- Limits ---
    max_files_per_request: int = 20
    max_file_bytes: int = 1_000_000  # 1 MB per file

    # --- Nested config groups ---
    rules: CustomRuleConfig = Field(default_factory=CustomRuleConfig)
    confidence: ConfidenceWeights = Field(default_factory=ConfidenceWeights)

    @property
    def use_real_llm(self) -> bool:
        """True only when a real OpenAI call should be attempted."""
        return bool(self.llm_enabled and self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton ``Settings`` instance.

    Cached so the (potentially file-reading) constructor runs once. Tests can
    clear the cache via ``get_settings.cache_clear()``.
    """
    return Settings()


# Convenience module-level handle for non-DI call sites.
settings = get_settings()
