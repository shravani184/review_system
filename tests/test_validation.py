"""Unit tests for the validation gatekeeper."""
import pytest

from app.utils.validation import (
    ValidationError,
    check_syntax,
    validate_filename,
    validate_size,
)


def test_validate_filename_accepts_py():
    assert validate_filename("module.py") == "module.py"


@pytest.mark.parametrize(
    "name",
    ["module.txt", "../etc/passwd.py", "a/b.py", "", None],
)
def test_validate_filename_rejects_bad(name):
    with pytest.raises(ValidationError):
        validate_filename(name)


def test_validate_size_rejects_empty_and_large():
    with pytest.raises(ValidationError):
        validate_size(b"", 100)
    with pytest.raises(ValidationError):
        validate_size(b"x" * 200, 100)
    validate_size(b"ok", 100)  # should not raise


def test_check_syntax_valid():
    res = check_syntax("x = 1\n")
    assert res.valid is True


def test_check_syntax_invalid_reports_line():
    res = check_syntax("def broken(:\n    pass\n")
    assert res.valid is False
    assert res.line == 1
    assert res.message
