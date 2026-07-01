"""AST parsing layer.

Parses Python source into an :class:`ast.Module` and extracts structured
metadata in a single traversal. The metadata is consumed by the custom rule
engine and is also useful for future features (call graphs, RAG indexing).

This layer performs **no** issue detection — it only describes structure.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class FunctionInfo:
    """Structural description of a function/method."""

    name: str
    lineno: int
    end_lineno: int
    args: list[str]
    has_docstring: bool
    decorators: list[str]
    returns_annotation: bool
    arg_annotations: dict[str, bool]  # arg name -> has annotation
    is_method: bool
    node: ast.AST = field(repr=False, default=None)  # type: ignore[assignment]


@dataclass
class ClassInfo:
    """Structural description of a class."""

    name: str
    lineno: int
    has_docstring: bool
    decorators: list[str]
    methods: list[FunctionInfo]


@dataclass
class ImportInfo:
    """A single imported name with its source line."""

    module: str
    alias: str | None
    lineno: int


@dataclass
class ModuleMetadata:
    """Aggregate structural metadata for one module."""

    has_module_docstring: bool
    imports: list[ImportInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)  # top-level
    assignments: list[int] = field(default_factory=list)         # line numbers
    loops: list[int] = field(default_factory=list)
    conditionals: list[int] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)               # callable names
    returns: list[int] = field(default_factory=list)
    tree: ast.Module = field(repr=False, default=None)           # type: ignore[assignment]


def _decorator_name(node: ast.expr) -> str:
    """Best-effort rendering of a decorator expression to a dotted name."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return "<expr>"


def _callable_name(node: ast.expr) -> str:
    """Best-effort rendering of a call target (e.g. ``os.system``)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_callable_name(node.value)}.{node.attr}"
    return "<call>"


def _build_function_info(node: ast.FunctionDef | ast.AsyncFunctionDef,
                         is_method: bool) -> FunctionInfo:
    args = [a.arg for a in node.args.args]
    args += [a.arg for a in node.args.kwonlyargs]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)

    # annotation presence per declared arg (ignoring self/cls)
    annotations: dict[str, bool] = {}
    for a in list(node.args.args) + list(node.args.kwonlyargs):
        if a.arg in ("self", "cls"):
            continue
        annotations[a.arg] = a.annotation is not None

    return FunctionInfo(
        name=node.name,
        lineno=node.lineno,
        end_lineno=getattr(node, "end_lineno", node.lineno) or node.lineno,
        args=args,
        has_docstring=ast.get_docstring(node) is not None,
        decorators=[_decorator_name(d) for d in node.decorator_list],
        returns_annotation=node.returns is not None,
        arg_annotations=annotations,
        is_method=is_method,
        node=node,
    )


class _MetadataVisitor(ast.NodeVisitor):
    """Single-pass collector of module-level structural metadata."""

    def __init__(self) -> None:
        self.imports: list[ImportInfo] = []
        self.classes: list[ClassInfo] = []
        self.functions: list[FunctionInfo] = []
        self.assignments: list[int] = []
        self.loops: list[int] = []
        self.conditionals: list[int] = []
        self.calls: list[str] = []
        self.returns: list[int] = []

    # -- imports --
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(ImportInfo(alias.name, alias.asname, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            full = f"{module}.{alias.name}" if module else alias.name
            self.imports.append(ImportInfo(full, alias.asname, node.lineno))

    # -- classes & functions --
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        methods = [
            _build_function_info(child, is_method=True)
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.classes.append(
            ClassInfo(
                name=node.name,
                lineno=node.lineno,
                has_docstring=ast.get_docstring(node) is not None,
                decorators=[_decorator_name(d) for d in node.decorator_list],
                methods=methods,
            )
        )
        # Descend to capture nested calls/loops, but methods are already recorded.
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Only record as a top-level function if not inside a class. The class
        # visitor records methods; here we detect via col_offset heuristic is
        # unreliable, so we record all and let callers distinguish via is_method.
        self.functions.append(_build_function_info(node, is_method=False))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    # -- statements --
    def visit_Assign(self, node: ast.Assign) -> None:
        self.assignments.append(node.lineno)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.loops.append(node.lineno)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.loops.append(node.lineno)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self.conditionals.append(node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(_callable_name(node.func))
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self.returns.append(node.lineno)
        self.generic_visit(node)


def parse_module(source: str) -> ModuleMetadata:
    """Parse ``source`` and return structured :class:`ModuleMetadata`.

    Raises :class:`SyntaxError` if the source does not parse — callers should
    run :func:`app.utils.validation.check_syntax` first to fail gracefully.
    """
    tree = ast.parse(source)
    visitor = _MetadataVisitor()
    visitor.visit(tree)

    # Top-level functions only: those whose parent is the module body.
    top_level = {id(n) for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    top_level_funcs = [f for f in visitor.functions if id(f.node) in top_level]

    return ModuleMetadata(
        has_module_docstring=ast.get_docstring(tree) is not None,
        imports=visitor.imports,
        classes=visitor.classes,
        functions=top_level_funcs,
        assignments=visitor.assignments,
        loops=visitor.loops,
        conditionals=visitor.conditionals,
        calls=visitor.calls,
        returns=visitor.returns,
        tree=tree,
    )
