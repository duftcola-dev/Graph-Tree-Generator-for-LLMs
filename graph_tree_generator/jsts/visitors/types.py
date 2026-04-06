"""Extract TypeScript interfaces, type aliases, and enums."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TypeMember:
    name: str
    type_hint: str | None = None


MAX_SOURCE_LEN = 2000


@dataclass
class TypeInfo:
    name: str
    kind: str  # "interface" | "type_alias" | "enum"
    members: list[TypeMember] = field(default_factory=list)
    extends: list[str] = field(default_factory=list)
    line: int = 0
    source_text: str | None = None


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_types(root_node, source: bytes) -> list[TypeInfo]:
    """Walk the AST and extract TypeScript type definitions."""
    types: list[TypeInfo] = []
    _walk_types(root_node, types)
    return types


def _walk_types(node, types: list[TypeInfo]):
    """Recursively walk looking for type definitions."""
    if node.type == "interface_declaration":
        info = _extract_interface(node)
        if info:
            types.append(info)
        return

    if node.type == "type_alias_declaration":
        info = _extract_type_alias(node)
        if info:
            types.append(info)
        return

    if node.type == "enum_declaration":
        info = _extract_enum(node)
        if info:
            types.append(info)
        return

    # Handle exported types: export interface/type/enum
    if node.type == "export_statement":
        for child in node.children:
            _walk_types(child, types)
        return

    for child in node.children:
        _walk_types(child, types)


def _extract_interface(node) -> TypeInfo | None:
    """Parse an interface_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    extends = []
    for child in node.children:
        if child.type == "extends_type_clause":
            for ext_child in child.children:
                if ext_child.type in ("type_identifier", "generic_type"):
                    extends.append(_text(ext_child))

    members = []
    body = node.child_by_field_name("body")
    if body:
        for member in body.children:
            if member.type in ("property_signature", "method_signature"):
                m_name = member.child_by_field_name("name")
                m_type = member.child_by_field_name("type")
                if m_name:
                    members.append(TypeMember(
                        name=_text(m_name),
                        type_hint=_truncate(_text(m_type)) if m_type else None,
                    ))

    return TypeInfo(
        name=_text(name_node),
        kind="interface",
        members=members,
        extends=extends,
        line=node.start_point[0] + 1,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )


def _extract_type_alias(node) -> TypeInfo | None:
    """Parse a type_alias_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    return TypeInfo(
        name=_text(name_node),
        kind="type_alias",
        line=node.start_point[0] + 1,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )


def _extract_enum(node) -> TypeInfo | None:
    """Parse an enum_declaration."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    members = []
    body = node.child_by_field_name("body")
    if body:
        for member in body.children:
            if member.type == "enum_member":
                m_name = member.child_by_field_name("name")
                if m_name:
                    members.append(TypeMember(name=_text(m_name)))

    return TypeInfo(
        name=_text(name_node),
        kind="enum",
        members=members,
        line=node.start_point[0] + 1,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )
