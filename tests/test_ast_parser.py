"""Unit tests for AST metadata extraction."""
from app.parser.ast_parser import parse_module

SOURCE = '''"""Module docstring."""
import os
from typing import List


GREETING = "hi"


class Greeter:
    """A greeter."""

    def greet(self, name: str) -> str:
        for _ in range(2):
            print(name)
        return name


def helper(a, b):
    if a:
        return b
    return a
'''


def test_extracts_module_docstring_and_imports():
    md = parse_module(SOURCE)
    assert md.has_module_docstring is True
    modules = {imp.module for imp in md.imports}
    assert "os" in modules
    assert "typing.List" in modules


def test_extracts_classes_and_methods():
    md = parse_module(SOURCE)
    assert len(md.classes) == 1
    cls = md.classes[0]
    assert cls.name == "Greeter"
    assert cls.has_docstring is True
    assert any(m.name == "greet" for m in cls.methods)


def test_extracts_top_level_functions_only():
    md = parse_module(SOURCE)
    names = {f.name for f in md.functions}
    assert "helper" in names
    # methods should not appear as top-level functions
    assert "greet" not in names


def test_extracts_control_flow_and_calls():
    md = parse_module(SOURCE)
    assert md.loops          # the for-loop
    assert md.conditionals   # the if
    assert "print" in md.calls
    assert md.returns        # return statements present
