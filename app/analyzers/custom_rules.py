"""Custom AST rule engine.

A small, extensible rule framework. Each rule is a class implementing
:class:`Rule`; the :class:`RuleEngine` runs every enabled rule and collects
:class:`RawFinding` objects. Thresholds come from
:class:`app.config.CustomRuleConfig`, so behaviour is configurable without
editing rule code (open/closed principle).

To add a rule: subclass :class:`Rule`, implement ``check``, and register it in
``DEFAULT_RULES``.
"""
from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from app.config import CustomRuleConfig
from app.parser.ast_parser import ModuleMetadata
from app.schemas.issue import RawFinding, ToolSource


@dataclass
class RuleContext:
    """Everything a rule needs to evaluate a single module."""

    source: str
    lines: list[str]
    metadata: ModuleMetadata
    config: CustomRuleConfig


class Rule(ABC):
    """Base class for a custom rule."""

    #: stable identifier surfaced as the finding's ``code``
    code: str = "CUSTOM"
    #: readable category surfaced as the finding's ``type``
    issue_type: str = "Custom Rule Violation"

    def enabled(self, config: CustomRuleConfig) -> bool:  # noqa: D401
        """Whether this rule should run given the config. Default: always."""
        return True

    @abstractmethod
    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        """Yield findings for the given module."""

    def _finding(self, line: int, message: str, severity: str = "warning",
                 column: int | None = None) -> RawFinding:
        return RawFinding(
            tool=ToolSource.CUSTOM,
            code=self.code,
            message=message,
            line=line,
            column=column,
            raw_severity=severity,
            extra={"type": self.issue_type},
        )


# --------------------------------------------------------------------------- #
# Complexity / size rules
# --------------------------------------------------------------------------- #
def _iter_functions(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


class MaxFunctionLengthRule(Rule):
    code = "CR001"
    issue_type = "Long Function"

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        limit = ctx.config.max_function_length
        for fn in _iter_functions(ctx.metadata.tree):
            start = fn.lineno
            end = getattr(fn, "end_lineno", start) or start
            length = end - start + 1
            if length > limit:
                yield self._finding(
                    start,
                    f"Function '{fn.name}' is {length} lines long "
                    f"(limit {limit}).",
                )


class MaxParametersRule(Rule):
    code = "CR002"
    issue_type = "Too Many Arguments"

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        limit = ctx.config.max_parameters
        for fn in _iter_functions(ctx.metadata.tree):
            count = len(fn.args.args) + len(fn.args.kwonlyargs)
            # don't count self/cls
            names = [a.arg for a in fn.args.args]
            if names and names[0] in ("self", "cls"):
                count -= 1
            if count > limit:
                yield self._finding(
                    fn.lineno,
                    f"Function '{fn.name}' takes {count} parameters "
                    f"(limit {limit}).",
                )


class MaxNestingDepthRule(Rule):
    code = "CR003"
    issue_type = "Deep Nesting"

    _NESTING = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor,
                ast.AsyncWith)

    def _depth(self, node: ast.AST, current: int = 0) -> int:
        deepest = current
        for child in ast.iter_child_nodes(node):
            nxt = current + 1 if isinstance(child, self._NESTING) else current
            deepest = max(deepest, self._depth(child, nxt))
        return deepest

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        limit = ctx.config.max_nesting_depth
        for fn in _iter_functions(ctx.metadata.tree):
            depth = self._depth(fn, 0)
            if depth > limit:
                yield self._finding(
                    fn.lineno,
                    f"Function '{fn.name}' nests {depth} levels deep "
                    f"(limit {limit}).",
                )


class CyclomaticComplexityRule(Rule):
    code = "CR004"
    issue_type = "Cyclomatic Complexity"

    # Nodes that introduce a new decision branch (McCabe).
    _DECISION = (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With,
                 ast.AsyncFor, ast.AsyncWith, ast.comprehension)

    def _complexity(self, fn: ast.AST) -> int:
        complexity = 1
        for node in ast.walk(fn):
            if isinstance(node, self._DECISION):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                # each extra operand adds a branch (a and b and c -> +2)
                complexity += len(node.values) - 1
            elif isinstance(node, ast.IfExp):  # ternary
                complexity += 1
        return complexity

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        limit = ctx.config.max_cyclomatic_complexity
        for fn in _iter_functions(ctx.metadata.tree):
            score = self._complexity(fn)
            if score > limit:
                yield self._finding(
                    fn.lineno,
                    f"Function '{fn.name}' has cyclomatic complexity {score} "
                    f"(limit {limit}).",
                    severity="error" if score > limit * 1.5 else "warning",
                )


class NestedLoopRule(Rule):
    code = "CR005"
    issue_type = "Nested Loops"

    def enabled(self, config: CustomRuleConfig) -> bool:
        return config.flag_nested_loops

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        loops = (ast.For, ast.While, ast.AsyncFor)
        for node in ast.walk(ctx.metadata.tree):
            if not isinstance(node, loops):
                continue
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, loops):
                    yield self._finding(
                        getattr(child, "lineno", node.lineno),
                        "Nested loop detected; consider refactoring or "
                        "vectorizing for readability and performance.",
                    )
                    break


# --------------------------------------------------------------------------- #
# Style / formatting rules
# --------------------------------------------------------------------------- #
class MaxLineLengthRule(Rule):
    code = "CR006"
    issue_type = "Line Too Long"

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        limit = ctx.config.max_line_length
        for i, line in enumerate(ctx.lines, start=1):
            length = len(line.rstrip("\n"))
            if length > limit:
                yield self._finding(
                    i, f"Line is {length} characters long (limit {limit}).",
                    severity="convention",
                )


class DuplicateImportsRule(Rule):
    code = "CR007"
    issue_type = "Duplicate Imports"

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        seen: dict[str, int] = {}
        for imp in ctx.metadata.imports:
            key = imp.alias or imp.module
            if key in seen:
                yield self._finding(
                    imp.lineno,
                    f"'{key}' is imported more than once "
                    f"(first at line {seen[key]}).",
                    severity="convention",
                )
            else:
                seen[key] = imp.lineno


class MissingTypeHintsRule(Rule):
    code = "CR008"
    issue_type = "Missing Type Hints"

    def enabled(self, config: CustomRuleConfig) -> bool:
        return config.enforce_type_hints

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        for fn in _iter_functions(ctx.metadata.tree):
            missing = [
                a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)
                if a.arg not in ("self", "cls") and a.annotation is None
            ]
            no_return = fn.returns is None
            if missing or no_return:
                detail = []
                if missing:
                    detail.append("parameters: " + ", ".join(missing))
                if no_return:
                    detail.append("return type")
                yield self._finding(
                    fn.lineno,
                    f"Function '{fn.name}' is missing type hints "
                    f"({'; '.join(detail)}).",
                    severity="convention",
                )


class MissingDocstringRule(Rule):
    code = "CR009"
    issue_type = "Missing Docstring"

    def enabled(self, config: CustomRuleConfig) -> bool:
        return config.enforce_docstrings

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        tree = ctx.metadata.tree
        if not ctx.metadata.has_module_docstring:
            yield self._finding(1, "Module is missing a docstring.",
                                severity="convention")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                if ast.get_docstring(node) is None:
                    kind = "Class" if isinstance(node, ast.ClassDef) else "Function"
                    yield self._finding(
                        node.lineno,
                        f"{kind} '{node.name}' is missing a docstring.",
                        severity="convention",
                    )


class MagicNumberRule(Rule):
    code = "CR010"
    issue_type = "Magic Number"

    # Numbers that are conventionally acceptable without explanation.
    _ALLOWED = {0, 1, 2, -1, 100}

    def enabled(self, config: CustomRuleConfig) -> bool:
        return config.flag_magic_numbers

    def check(self, ctx: RuleContext) -> Iterable[RawFinding]:
        for node in ast.walk(ctx.metadata.tree):
            if not isinstance(node, ast.Constant):
                continue
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if value in self._ALLOWED:
                continue
            # Skip numbers used as default arg values / constants assigned to
            # an UPPER_CASE name (treated as named constants) is hard to detect
            # cheaply here, so we keep it simple and let confidence reflect it.
            yield self._finding(
                getattr(node, "lineno", 0),
                f"Magic number {value!r} should be a named constant.",
                severity="convention",
            )


# Registry consumed by the engine. Order here is the order findings appear in
# before normalization/sorting.
DEFAULT_RULES: list[Rule] = [
    MaxFunctionLengthRule(),
    MaxParametersRule(),
    MaxNestingDepthRule(),
    CyclomaticComplexityRule(),
    NestedLoopRule(),
    MaxLineLengthRule(),
    DuplicateImportsRule(),
    MissingTypeHintsRule(),
    MissingDocstringRule(),
    MagicNumberRule(),
]


class RuleEngine:
    """Runs a collection of rules against a module."""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        self._rules = rules if rules is not None else DEFAULT_RULES

    def run(self, source: str, metadata: ModuleMetadata,
            config: CustomRuleConfig) -> list[RawFinding]:
        """Execute every enabled rule and return collected findings."""
        ctx = RuleContext(
            source=source,
            lines=source.splitlines(),
            metadata=metadata,
            config=config,
        )
        findings: list[RawFinding] = []
        for rule in self._rules:
            if not rule.enabled(config):
                continue
            findings.extend(rule.check(ctx))
        return findings
