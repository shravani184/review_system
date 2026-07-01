"""Integration tests for the end-to-end review service (offline mode)."""
from app.config import Settings
from app.llm.client import Explanation, Explainer
from app.review_service import ReviewService, SourceFile
from app.schemas.issue import NormalizedFinding


def _offline_settings() -> Settings:
    return Settings(llm_enabled=False, openai_api_key=None)


def test_detects_hardcoded_password_and_undefined_variable():
    svc = ReviewService(_offline_settings())
    source = b'password = "admin123"\n\n\ndef login():\n    print(user)\n'
    review = svc.review_file(SourceFile("sample.py", source))

    assert review.syntax_valid is True
    types = {i.type for i in review.issues}
    assert "Hardcoded Password" in types
    assert "Undefined Variable" in types

    # The spec's two headline findings must be High severity.
    for issue in review.issues:
        if issue.type in ("Hardcoded Password", "Undefined Variable"):
            assert issue.severity.value == "High"
            assert 0.0 <= issue.confidence <= 1.0


def test_rejects_invalid_python():
    svc = ReviewService(_offline_settings())
    review = svc.review_file(SourceFile("bad.py", b"def broken(:\n  pass\n"))
    assert review.syntax_valid is False
    assert review.error and "Syntax error" in review.error
    assert review.issues == []


def test_rejects_non_python_file():
    svc = ReviewService(_offline_settings())
    review = svc.review_file(SourceFile("notes.txt", b"hello"))
    assert review.syntax_valid is False
    assert review.issues == []


def test_clean_code_yields_no_issues():
    svc = ReviewService(_offline_settings())
    clean = (
        b'"""A clean module."""\n\n\n'
        b"def add(left: int, right: int) -> int:\n"
        b'    """Return the sum of two integers."""\n'
        b"    return left + right\n"
    )
    review = svc.review_file(SourceFile("clean.py", clean))
    assert review.syntax_valid is True
    assert review.issue_count == 0


def test_no_hallucination_contract():
    """The explainer must never produce more issues than verified findings.

    We inject a malicious explainer that *tries* to add extra explanations for
    indexes that don't exist; merge must ignore them because issues are built
    strictly from the verified findings list.
    """

    class RogueExplainer(Explainer):
        mode = "offline"

        def explain(self, source: str,
                    findings: list[NormalizedFinding]) -> dict:
            out = {
                i: Explanation("real", "fix", 0.9)
                for i in range(len(findings))
            }
            # attempt to inject phantom issues at out-of-range indexes
            out[999] = Explanation("phantom bug", "phantom fix", 0.99)
            return out

    svc = ReviewService(_offline_settings(), explainer=RogueExplainer())
    source = b'password = "admin123"\n'
    review = svc.review_file(SourceFile("x.py", source))
    explanations = [i.explanation for i in review.issues]
    assert "phantom bug" not in explanations
