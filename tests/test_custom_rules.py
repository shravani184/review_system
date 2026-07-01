"""Unit tests for the custom AST rule engine."""
from app.analyzers.custom_rules import (
    CyclomaticComplexityRule,
    DuplicateImportsRule,
    MaxParametersRule,
    NestedLoopRule,
    RuleEngine,
)
from app.config import CustomRuleConfig
from app.parser.ast_parser import parse_module


def _run(rule, source, config=None):
    config = config or CustomRuleConfig()
    md = parse_module(source)
    from app.analyzers.custom_rules import RuleContext
    ctx = RuleContext(source, source.splitlines(), md, config)
    return list(rule.check(ctx))


def test_max_parameters_rule():
    src = "def f(a, b, c, d, e, f, g):\n    return a\n"
    config = CustomRuleConfig(max_parameters=5)
    findings = _run(MaxParametersRule(), src, config)
    assert len(findings) == 1
    assert "parameters" in findings[0].message


def test_max_parameters_ignores_self():
    src = "class C:\n    def m(self, a, b, c, d, e):\n        return a\n"
    config = CustomRuleConfig(max_parameters=5)
    # 5 real params (a..e) == limit, so no finding
    assert _run(MaxParametersRule(), src, config) == []


def test_duplicate_imports_rule():
    src = "import os\nimport os\n"
    findings = _run(DuplicateImportsRule(), src)
    assert len(findings) == 1
    assert "imported more than once" in findings[0].message


def test_nested_loop_rule():
    src = "def f():\n    for i in range(3):\n        for j in range(3):\n            print(i, j)\n"
    findings = _run(NestedLoopRule(), src)
    assert len(findings) >= 1
    assert findings[0].extra["type"] == "Nested Loops"


def test_cyclomatic_complexity_rule():
    branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(12))
    src = f"def f(x):\n{branches}\n    return -1\n"
    config = CustomRuleConfig(max_cyclomatic_complexity=10)
    findings = _run(CyclomaticComplexityRule(), src, config)
    assert len(findings) == 1
    assert "complexity" in findings[0].message.lower()


def test_engine_respects_disabled_rules():
    src = "import os\n\n\ndef f(a):\n    return a\n"
    # Disable docstrings, type hints, magic numbers to isolate behaviour
    config = CustomRuleConfig(
        enforce_docstrings=False,
        enforce_type_hints=False,
        flag_magic_numbers=False,
        flag_nested_loops=False,
    )
    md = parse_module(src)
    findings = RuleEngine().run(src, md, config)
    types = {f.extra["type"] for f in findings}
    assert "Missing Docstring" not in types
    assert "Missing Type Hints" not in types
