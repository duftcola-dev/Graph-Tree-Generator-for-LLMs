"""Extract function/method/arrow definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


MAX_SOURCE_LEN = 2000


@dataclass
class FunctionInfo:
    name: str
    kind: str  # "declaration" | "expression" | "arrow" | "method" | "generator"
    async_: bool = False
    params: list[str] = field(default_factory=list)
    line: int = 0
    enclosing_class: str | None = None
    source_text: str | None = None


def _text(node) -> str:
    return node.text.decode("utf-8")


def extract_functions(root_node, source: bytes) -> list[FunctionInfo]:
    """Walk the AST and extract all function definitions."""
    functions: list[FunctionInfo] = []
    _walk_functions(root_node, functions, enclosing_class=None)
    return functions


def _walk_functions(node, functions: list[FunctionInfo], enclosing_class: str | None):
    """Recursively walk looking for function definitions."""

    # function foo() {} / async function foo() {}
    if node.type in ("function_declaration", "generator_function_declaration"):
        info = _extract_function_decl(node, enclosing_class)
        if info:
            functions.append(info)
        # Don't recurse into function body for nested function defs
        # (we do want them — they become separate entries)
        for child in node.children:
            if child.type == "statement_block":
                _walk_functions(child, functions, enclosing_class)
        return

    # Arrow function: const foo = () => {} or const foo = async () => {}
    if node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value and value.type in ("arrow_function", "function_expression"):
            name_node = node.child_by_field_name("name")
            name = _text(name_node) if name_node and name_node.type == "identifier" else "anonymous"
            info = _extract_func_node(value, name, enclosing_class)
            if info:
                functions.append(info)
            # Recurse into body
            body = value.child_by_field_name("body")
            if body:
                _walk_functions(body, functions, enclosing_class)
            return

    # Class method: method_definition inside class body
    if node.type == "method_definition":
        info = _extract_method(node, enclosing_class)
        if info:
            functions.append(info)
        body = node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class)
        return

    # Track class context
    if node.type in ("class_declaration", "class_expression"):
        name_node = node.child_by_field_name("name")
        cls_name = _text(name_node) if name_node else "anonymous"
        body = node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class=cls_name)
        return

    for child in node.children:
        _walk_functions(child, functions, enclosing_class)


def _extract_function_decl(node, enclosing_class: str | None) -> FunctionInfo | None:
    """Extract from function_declaration / generator_function_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    is_async = any(c.type == "async" or _text(c) == "async" for c in node.children if c.type != "statement_block")
    is_generator = node.type == "generator_function_declaration"

    return FunctionInfo(
        name=_text(name_node),
        kind="generator" if is_generator else "declaration",
        async_=is_async,
        params=_extract_params(node),
        line=node.start_point[0] + 1,
        enclosing_class=enclosing_class,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )


def _extract_func_node(node, name: str, enclosing_class: str | None) -> FunctionInfo:
    """Extract from arrow_function or function_expression."""
    is_async = any(_text(c) == "async" for c in node.children if c.type != "statement_block")
    kind = "arrow" if node.type == "arrow_function" else "expression"

    return FunctionInfo(
        name=name,
        kind=kind,
        async_=is_async,
        params=_extract_params(node),
        line=node.start_point[0] + 1,
        enclosing_class=enclosing_class,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )


def _extract_method(node, enclosing_class: str | None) -> FunctionInfo | None:
    """Extract from method_definition."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    is_async = any(_text(c) == "async" for c in node.children if c.type not in ("statement_block", "formal_parameters"))

    return FunctionInfo(
        name=_text(name_node),
        kind="method",
        async_=is_async,
        params=_extract_params(node),
        line=node.start_point[0] + 1,
        enclosing_class=enclosing_class,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )


def _extract_params(node) -> list[str]:
    """Extract parameter names from a function/method node."""
    params_node = node.child_by_field_name("parameters")
    if not params_node:
        return []

    params = []
    for child in params_node.children:
        if child.type == "identifier":
            params.append(_text(child))
        elif child.type in ("required_parameter", "optional_parameter"):
            # TypeScript parameter with type annotation
            pattern = child.child_by_field_name("pattern")
            if pattern:
                params.append(_text(pattern))
        elif child.type in ("object_pattern", "array_pattern"):
            params.append("{...}" if child.type == "object_pattern" else "[...]")
        elif child.type == "assignment_pattern":
            left = child.child_by_field_name("left")
            if left:
                params.append(_text(left))
        elif child.type == "rest_pattern":
            arg = child.children[1] if len(child.children) > 1 else None
            if arg:
                params.append(f"...{_text(arg)}")
    return params
