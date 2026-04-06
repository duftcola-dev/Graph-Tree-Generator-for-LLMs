"""Extract class declarations with methods and properties."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PropertyInfo:
    name: str
    value_hint: str | None = None
    line: int = 0


@dataclass
class MethodBrief:
    name: str
    async_: bool = False
    line: int = 0


MAX_SOURCE_LEN = 2000


@dataclass
class ClassInfo:
    name: str
    extends: str | None = None
    methods: list[MethodBrief] = field(default_factory=list)
    properties: list[PropertyInfo] = field(default_factory=list)
    line: int = 0
    source_text: str | None = None


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_classes(root_node, source: bytes) -> list[ClassInfo]:
    """Walk the AST and extract class declarations."""
    classes: list[ClassInfo] = []
    _walk_classes(root_node, classes)
    return classes


def _walk_classes(node, classes: list[ClassInfo]):
    """Recursively walk looking for class definitions."""
    if node.type in ("class_declaration", "class_expression"):
        info = _extract_class(node)
        if info:
            classes.append(info)
        return  # don't recurse into class body (methods handled above)

    # Also catch: const X = class { ... }
    if node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        if value and value.type == "class_expression":
            name_node = node.child_by_field_name("name")
            info = _extract_class(value)
            if info and name_node:
                info.name = _text(name_node)
                classes.append(info)
            return

    for child in node.children:
        _walk_classes(child, classes)


def _extract_class(node) -> ClassInfo | None:
    """Parse a class_declaration or class_expression."""
    name_node = node.child_by_field_name("name")
    name = _text(name_node) if name_node else "anonymous"

    # extends clause
    extends = None
    for child in node.children:
        if child.type == "class_heritage":
            for heritage_child in child.children:
                if heritage_child.type == "extends_clause":
                    for ext_child in heritage_child.children:
                        if ext_child.type in ("identifier", "member_expression"):
                            extends = _text(ext_child)

    # Methods and properties from class body
    methods: list[MethodBrief] = []
    properties: list[PropertyInfo] = []
    body = node.child_by_field_name("body")
    if body:
        for member in body.children:
            if member.type == "method_definition":
                m_name_node = member.child_by_field_name("name")
                if m_name_node:
                    is_async = any(_text(c) == "async" for c in member.children if c.type not in ("statement_block", "formal_parameters"))
                    methods.append(MethodBrief(
                        name=_text(m_name_node),
                        async_=is_async,
                        line=member.start_point[0] + 1,
                    ))
            elif member.type in ("public_field_definition", "field_definition", "property_definition"):
                p_name_node = member.child_by_field_name("name")
                p_value_node = member.child_by_field_name("value")
                if p_name_node:
                    properties.append(PropertyInfo(
                        name=_text(p_name_node),
                        value_hint=_truncate(_text(p_value_node)) if p_value_node else None,
                        line=member.start_point[0] + 1,
                    ))

    return ClassInfo(
        name=name,
        extends=extends,
        methods=methods,
        properties=properties,
        line=node.start_point[0] + 1,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )
