"""Integration tests for the FastAPI endpoints."""
import os

# Force offline explainer for deterministic tests before app import.
os.environ["LLM_ENABLED"] = "false"
os.environ.pop("OPENAI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app  # noqa: E402

client = TestClient(app)


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["analyzers"]["pylint"] is True
    assert body["analyzers"]["bandit"] is True
    assert body["llm_mode"] == "offline"


def test_root_endpoint():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "endpoints" in resp.json()


def test_review_single_file():
    src = b'password = "admin123"\n\n\ndef login():\n    print(user)\n'
    resp = client.post(
        "/review",
        files=[("files", ("sample.py", src, "text/x-python"))],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["files"]) == 1
    types = {i["type"] for i in body["files"][0]["issues"]}
    assert "Hardcoded Password" in types
    assert "Undefined Variable" in types
    assert body["total_issues"] >= 2


def test_review_multiple_files():
    f1 = b'import os\nimport os\n'
    f2 = b'x = eval("1+1")\n'
    resp = client.post(
        "/review",
        files=[
            ("files", ("a.py", f1, "text/x-python")),
            ("files", ("b.py", f2, "text/x-python")),
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["files"]) == 2
    filenames = {f["filename"] for f in body["files"]}
    assert filenames == {"a.py", "b.py"}


def test_review_rejects_invalid_python_per_file():
    resp = client.post(
        "/review",
        files=[("files", ("bad.py", b"def broken(:\n  pass\n", "text/x-python"))],
    )
    assert resp.status_code == 200
    file_review = resp.json()["files"][0]
    assert file_review["syntax_valid"] is False
    assert file_review["error"]


def test_review_requires_files():
    resp = client.post("/review", files=[])
    # FastAPI returns 422 when the required 'files' field is missing/empty.
    assert resp.status_code in (400, 422)
