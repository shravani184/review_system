# Hybrid LLM-Based Code Review System

**Neuro-symbolic code review for Python.** Deterministic static analysis detects
issues; a Large Language Model only *explains* the verified findings. This
separation is the core design principle — it gives you the recall and grounding
of symbolic tools with the readability of LLM explanations, while structurally
preventing the LLM from hallucinating bugs.

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [System Flow](#system-flow)
4. [Folder Structure](#folder-structure)
5. [Requirements](#requirements)
6. [Installation](#installation)
7. [Running the Service](#running-the-service)
8. [API Documentation](#api-documentation)
9. [Example Request & Response](#example-request--response)
10. [Configuration](#configuration)
11. [Testing](#testing)
12. [Docker](#docker)
13. [Design Principles](#design-principles)
14. [Future Work](#future-work)

---

## Project Overview

The system reviews uploaded Python files and returns structured JSON describing
each issue, with a plain-language explanation, a concrete fix suggestion, and a
confidence score.

The guiding philosophy:

* **Symbolic analysis is the source of truth.** Pylint, Bandit, and a custom AST
  rule engine perform *all* detection.
* **The LLM is an explanation and recommendation engine.** It receives the code
  plus the closed list of verified findings and explains *only* those. It never
  performs primary bug detection in the MVP and is instructed not to invent
  issues.

If no API key is configured, the system runs in a deterministic **offline
explainer** mode using a curated template knowledge base — so it is fully usable
and testable with zero external dependencies, while preserving the
no-hallucination guarantee.

### What it detects
Undefined / unused variables, unused & duplicate imports, syntax errors, missing
docstrings, naming-convention violations, long functions, too many arguments,
nested loops, high cyclomatic complexity, deep nesting, dead code, magic numbers,
missing type hints, over-long lines — plus security issues via Bandit: hardcoded
passwords, `eval`/`exec`, unsafe `subprocess`, weak cryptography, shell injection,
and basic SQL-injection patterns.

---

## Architecture

```
            ┌──────────────────────── FastAPI (app/api) ────────────────────────┐
            │           POST /review   ·   GET /health   ·   GET /              │
            └───────────────────────────────┬──────────────────────────────────┘
                                             ▼
                          Preprocessing & Validation (utils)
                                             ▼
                              AST Parser (parser) — metadata
                                             ▼
        ┌──────────────── Symbolic Analysis  =  SOURCE OF TRUTH ────────────────┐
        │   Pylint runner   ·   Bandit runner   ·   Custom AST Rule Engine       │
        └───────────────────────────────┬──────────────────────────────────────┘
                                         ▼
                         Normalization Layer → common schema
                                         ▼
                LLM Reasoning Layer (OpenAI OR offline) — explain only
                                         ▼
                 Confidence Engine  (0.5·tool + 0.3·llm + 0.2·rule)
                                         ▼
                  Output Aggregation (dedupe + sort) → strict JSON
```

Each module has a single responsibility and depends only on the shared schema
and (where reasonable) injected collaborators, following SOLID principles.

---

## System Flow

1. **Receive** one or more `.py` files via `POST /review` (multipart).
2. **Validate** filename, size, and Python syntax. Invalid files are rejected
   per-file (the batch still succeeds for the rest). A per-request temp
   workspace is created and auto-cleaned.
3. **Parse** the source with `ast` and extract structural metadata (imports,
   classes, functions, variables, loops, conditionals, calls, decorators,
   returns).
4. **Detect** with Pylint + Bandit + the custom rule engine. *No LLM here.*
5. **Normalize** every tool's output into one schema with unified severity and a
   per-finding reliability score.
6. **Explain** the verified findings with the LLM (or offline explainer).
7. **Score** each finding with the confidence engine.
8. **Aggregate** — deduplicate cross-tool overlaps, sort by severity, emit JSON.

---

## Folder Structure

```
review_system/
├── app/
│   ├── __init__.py
│   ├── config.py                 # pydantic-settings configuration
│   ├── review_service.py         # pipeline orchestration (use-case layer)
│   ├── api/
│   │   └── main.py               # FastAPI app: /review, /health, /
│   ├── parser/
│   │   └── ast_parser.py         # AST metadata extraction
│   ├── analyzers/
│   │   ├── pylint_runner.py      # Pylint detector
│   │   ├── bandit_runner.py      # Bandit (security) detector
│   │   └── custom_rules.py       # configurable AST rule engine
│   ├── normalizer/
│   │   └── normalize.py          # map all outputs to common schema
│   ├── llm/
│   │   ├── prompt.py             # explain-only prompt construction
│   │   └── client.py             # Explainer: OpenAI + offline + factory
│   ├── aggregator/
│   │   ├── confidence.py         # weighted confidence engine
│   │   └── merge.py              # dedupe + assemble final issues
│   ├── schemas/
│   │   └── issue.py              # pydantic contract between layers
│   └── utils/
│       ├── logging_config.py
│       ├── validation.py
│       └── file_utils.py         # temp workspace manager
├── tests/                        # unit + integration tests
├── examples/
│   ├── sample_input.py
│   └── sample_output.json
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── run.py
└── README.md
```

---

## Requirements

* Python 3.11+
* See `requirements.txt` (FastAPI, Pydantic v2, Pylint, Bandit, httpx, pytest)
* Optional: an OpenAI API key for LLM-backed explanations

---

## Installation

```bash
git clone <your-repo-url> review_system
cd review_system

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env               # then edit as needed
```

---

## Running the Service

```bash
# Option A: convenience script (auto-reload)
python run.py

# Option B: uvicorn directly (production-style)
uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Interactive API docs are then available at `http://localhost:8000/docs`.

Running **without** an `OPENAI_API_KEY` uses the offline explainer automatically.

---

## API Documentation

### `POST /review`
Review one or more Python files.

* **Body:** `multipart/form-data` with one or many `files` parts.
* **Returns:** `ReviewResponse` (strict JSON).

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `ok` |
| `total_issues` | int | Total verified issues across all files |
| `llm_mode` | string | `openai` or `offline` |
| `files[]` | array | One `FileReview` per uploaded file |
| `files[].filename` | string | Original filename |
| `files[].syntax_valid` | bool | Whether the file parsed |
| `files[].error` | string? | Rejection reason, if any |
| `files[].issues[]` | array | Verified, explained issues |

Each issue: `tool`, `type`, `severity`, `line`, `column`, `code`, `message`,
`explanation`, `suggestion`, `confidence` (0.0–1.0).

### `GET /health`
Returns service status, LLM mode, and analyzer availability.

### `GET /`
Returns basic service metadata.

---

## Example Request & Response

**Request**

```bash
curl -X POST http://localhost:8000/review \
  -F "files=@examples/sample_input.py"
```

`examples/sample_input.py`

```python
password = "admin123"


def login():
    print(user)
```

**Response (abridged)**

```json
{
  "status": "ok",
  "llm_mode": "offline",
  "total_issues": 6,
  "files": [
    {
      "filename": "sample_input.py",
      "syntax_valid": true,
      "issue_count": 6,
      "issues": [
        {
          "tool": "Bandit",
          "type": "Hardcoded Password",
          "severity": "High",
          "line": 1,
          "explanation": "A credential appears to be embedded directly in the source code, which exposes it to anyone with repository access.",
          "suggestion": "Move the secret into an environment variable or a secrets manager and read it at runtime.",
          "confidence": 0.935
        },
        {
          "tool": "Pylint",
          "type": "Undefined Variable",
          "severity": "High",
          "line": 5,
          "explanation": "This name is used before it is assigned or imported in the current scope, so it will raise a NameError at runtime.",
          "suggestion": "Define, import, or pass the variable before it is referenced.",
          "confidence": 0.935
        }
      ]
    }
  ]
}
```

The full output is in `examples/sample_output.json`.

---

## Configuration

All settings are environment-overridable (see `.env.example`). Highlights:

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENAI_API_KEY` | *(empty)* | Empty ⇒ offline explainer mode |
| `OPENAI_MODEL` | `gpt-4o-mini` | Chat model for explanations |
| `RULE_MAX_FUNCTION_LENGTH` | `50` | Long-function threshold |
| `RULE_MAX_PARAMETERS` | `5` | Too-many-arguments threshold |
| `RULE_MAX_NESTING_DEPTH` | `4` | Deep-nesting threshold |
| `RULE_MAX_CYCLOMATIC_COMPLEXITY` | `10` | Complexity threshold |
| `RULE_MAX_LINE_LENGTH` | `100` | Line-length threshold |
| `CONF_STATIC_TOOL_WEIGHT` | `0.5` | Confidence weight: tool |
| `CONF_LLM_AGREEMENT_WEIGHT` | `0.3` | Confidence weight: LLM |
| `CONF_RULE_RELIABILITY_WEIGHT` | `0.2` | Confidence weight: rule |

**Confidence formula:**
`confidence = 0.5·static_tool_score + 0.3·llm_agreement + 0.2·rule_reliability`,
clamped to `[0, 1]`.

---

## Testing

```bash
pytest -q
```

Covers validation, AST parsing, every custom rule, normalization, the confidence
engine, the full pipeline, the no-hallucination contract, and the HTTP endpoints.

---

## Docker

```bash
# Build & run with compose (reads .env)
docker compose up --build

# Or plain Docker
docker build -t hybrid-code-review .
docker run -p 8000:8000 --env-file .env hybrid-code-review
```

---

## Design Principles

* **Neuro-symbolic separation.** Detection and explanation live in different
  layers connected only by a typed schema; the LLM cannot add issues.
* **Single responsibility / SOLID.** Each module does one thing; the rule engine
  is open for extension (add a `Rule` subclass) and closed for modification.
* **Dependency injection.** The explainer and rule engine are injected into the
  service; the service is injected into the API — trivially mockable in tests.
* **Graceful degradation.** A failing analyzer or LLM call never fails the whole
  request; it logs and continues.

---

## Future Work

The architecture is designed to absorb these without structural change:

* Repository-level analysis; GitHub/GitLab PR integration; CI/CD gating.
* VS Code extension; multi-language support (Java, JS, C++, Go, Rust) by adding
  language-specific parser + analyzer adapters behind the same schema.
* Automatic fix / diff-patch generation; separate (clearly-labeled) AI
  suggestions distinct from verified findings.
* Vector database + RAG over an OWASP secure-coding knowledge base and
  organization-specific standards.
* Historical review memory, trend analysis, and a repository-health dashboard.
* A fine-tuned explanation model.
```
