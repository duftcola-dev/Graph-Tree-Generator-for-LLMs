"""Extract function and method definitions from Python AST."""

from __future__ import annotations

from dataclasses import dataclass, field


MAX_SOURCE_LEN = 2000


@dataclass
class FunctionInfo:
    name: str
    kind: str  # "function" | "method" | "staticmethod" | "classmethod" | "property"
    async_: bool = False
    params: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    line: int = 0
    enclosing_class: str | None = None
    source_text: str | None = None


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_functions(root_node, source: bytes) -> list[FunctionInfo]:
    """Walk the AST and extract all function definitions."""
    functions: list[FunctionInfo] = []
    _walk_functions(root_node, functions, enclosing_class=None)
    return functions


def _walk_functions(node, functions: list[FunctionInfo], enclosing_class: str | None):
    """Recursively walk looking for function definitions."""
    if node.type in ("function_definition", "decorated_definition"):
        info = _extract_function(node, enclosing_class)
        if info:
            functions.append(info)
        # Recurse into the function body for nested functions
        func_node = node
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type in ("function_definition", "class_definition"):
                    func_node = child
                    break
        body = func_node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class)
        return

    # Track class context
    if node.type == "class_definition":
        name_node = node.child_by_field_name("name")
        cls_name = _text(name_node) if name_node else "anonymous"
        body = node.child_by_field_name("body")
        if body:
            _walk_functions(body, functions, enclosing_class=cls_name)
        return

    for child in node.children:
        _walk_functions(child, functions, enclosing_class)


def _extract_function(node, enclosing_class: str | None) -> FunctionInfo | None:
    """Extract from function_definition or decorated_definition."""
    decorators: list[str] = []
    func_node = node

    if node.type == "decorated_definition":
        for child in node.children:
            if child.type == "decorator":
                dec_text = _text(child).lstrip("@").strip()
                decorators.append(dec_text)
            elif child.type == "function_definition":
                func_node = child
                break
            elif child.type == "class_definition":
                # This is a decorated class, not a function
                return None

    name_node = func_node.child_by_field_name("name")
    if not name_node:
        return None

    is_async = any(
        child.type == "async" or _text(child) == "async"
        for child in func_node.children
        if child.type not in ("block", "parameters")
    )

    # Determine kind based on decorators and context
    kind = "function"
    if enclosing_class:
        kind = "method"
        for dec in decorators:
            if dec == "staticmethod":
                kind = "staticmethod"
                break
            elif dec == "classmethod":
                kind = "classmethod"
                break
            elif dec == "property" or dec.endswith(".setter") or dec.endswith(".getter") or dec.endswith(".deleter"):
                kind = "property"
                break

    return FunctionInfo(
        name=_text(name_node),
        kind=kind,
        async_=is_async,
        params=_extract_params(func_node),
        decorators=decorators,
        line=node.start_point[0] + 1,
        enclosing_class=enclosing_class,
        source_text=func_node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )


def _extract_params(node) -> list[str]:
    """Extract parameter names from a function node."""
    params_node = node.child_by_field_name("parameters")
    if not params_node:
        return []

    params = []
    for child in params_node.children:
        if child.type == "identifier":
            params.append(_text(child))
        elif child.type == "typed_parameter":
            name = child.children[0] if child.children else None
            if name:
                params.append(_text(name))
        elif child.type == "default_parameter":
            name_node = child.child_by_field_name("name")
            if name_node:
                params.append(_text(name_node))
        elif child.type == "typed_default_parameter":
            name_node = child.child_by_field_name("name")
            if name_node:
                params.append(_text(name_node))
        elif child.type == "list_splat_pattern":
            arg = child.children[0] if child.children else None
            if arg:
                params.append(f"*{_text(arg)}")
        elif child.type == "dictionary_splat_pattern":
            arg = child.children[0] if child.children else None
            if arg:
                params.append(f"**{_text(arg)}")
    return params
