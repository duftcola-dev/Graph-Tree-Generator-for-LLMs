"""Extract ESM imports and CommonJS require() calls."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportSpecifier:
    name: str  # imported name (or "default" / "namespace")
    alias: str | None = None  # local binding name if renamed


@dataclass
class ImportInfo:
    source: str  # module specifier string
    specifiers: list[ImportSpecifier] = field(default_factory=list)
    line: int = 0
    kind: str = "esm"  # "esm" | "cjs"


def _text(node) -> str:
    return node.text.decode("utf-8")


def _strip_quotes(s: str) -> str:
    return s.strip("'\"`")


def extract_imports(root_node, source: bytes) -> list[ImportInfo]:
    """Walk the AST and extract all import/require declarations."""
    imports: list[ImportInfo] = []
    _walk_imports(root_node, imports)
    return imports


def _walk_imports(node, imports: list[ImportInfo]):
    """Recursively walk the tree looking for import patterns."""
    # ESM: import ... from "source"
    if node.type == "import_statement":
        imp = _extract_esm_import(node)
        if imp:
            imports.append(imp)
        return  # don't recurse into import statement children

    # CJS: require("source") — could be in variable_declarator or standalone
    if node.type == "call_expression":
        func = node.child_by_field_name("function")
        if func and func.type == "identifier" and _text(func) == "require":
            imp = _extract_cjs_require(node)
            if imp:
                imports.append(imp)
            return

    # Also catch: require("express").Router()  →  member access on require
    if node.type == "call_expression":
        func = node.child_by_field_name("function")
        if func and func.type == "member_expression":
            obj = func.child_by_field_name("object")
            if obj and obj.type == "call_expression":
                inner_func = obj.child_by_field_name("function")
                if inner_func and inner_func.type == "identifier" and _text(inner_func) == "require":
                    imp = _extract_cjs_require(obj)
                    if imp:
                        imports.append(imp)

    for child in node.children:
        _walk_imports(child, imports)


def _extract_esm_import(node) -> ImportInfo | None:
    """Parse an ESM import_statement node."""
    source_node = node.child_by_field_name("source")
    if not source_node:
        return None

    source = _strip_quotes(_text(source_node))
    specifiers: list[ImportSpecifier] = []

    for child in node.children:
        # import X from "..."  →  default import
        if child.type == "import_clause":
            for sub in child.children:
                if sub.type == "identifier":
                    specifiers.append(ImportSpecifier(name="default", alias=_text(sub)))
                elif sub.type == "named_imports":
                    for spec in sub.children:
                        if spec.type == "import_specifier":
                            name_node = spec.child_by_field_name("name")
                            alias_node = spec.child_by_field_name("alias")
                            if name_node:
                                specifiers.append(ImportSpecifier(
                                    name=_text(name_node),
                                    alias=_text(alias_node) if alias_node else None,
                                ))
                elif sub.type == "namespace_import":
                    # import * as X from "..."
                    for ns_child in sub.children:
                        if ns_child.type == "identifier":
                            specifiers.append(ImportSpecifier(
                                name="namespace",
                                alias=_text(ns_child),
                            ))

    return ImportInfo(
        source=source,
        specifiers=specifiers,
        line=node.start_point[0] + 1,
        kind="esm",
    )


def _extract_cjs_require(call_node) -> ImportInfo | None:
    """Parse a require("...") call expression node."""
    args = call_node.child_by_field_name("arguments")
    if not args:
        return None

    # Find the first string argument
    source = None
    for arg in args.children:
        if arg.type in ("string", "template_string"):
            source = _strip_quotes(_text(arg))
            break

    if not source:
        return None  # dynamic require — skip

    # Walk up to find binding context
    specifiers: list[ImportSpecifier] = []
    parent = call_node.parent

    # const X = require("...") or const X = require("...").Router()
    if parent and parent.type in ("variable_declarator", "assignment_expression"):
        if parent.type == "variable_declarator":
            name_node = parent.child_by_field_name("name")
        else:
            name_node = parent.child_by_field_name("left")

        if name_node:
            if name_node.type == "identifier":
                specifiers.append(ImportSpecifier(name="default", alias=_text(name_node)))
            elif name_node.type in ("object_pattern", "object"):
                # const { a, b } = require("...")
                for prop in name_node.children:
                    if prop.type in ("shorthand_property_identifier_pattern",
                                     "shorthand_property_identifier"):
                        specifiers.append(ImportSpecifier(name=_text(prop)))
                    elif prop.type == "pair_pattern":
                        key = prop.child_by_field_name("key")
                        value = prop.child_by_field_name("value")
                        if key and value:
                            specifiers.append(ImportSpecifier(
                                name=_text(key),
                                alias=_text(value),
                            ))

    # If the parent is a member_expression (require("express").Router()),
    # the actual binding is in the grandparent variable_declarator
    if parent and parent.type == "member_expression":
        grandparent = parent.parent
        if grandparent and grandparent.type == "call_expression":
            great = grandparent.parent
            if great and great.type == "variable_declarator":
                name_node = great.child_by_field_name("name")
                if name_node and name_node.type == "identifier":
                    specifiers = [ImportSpecifier(name="default", alias=_text(name_node))]

    return ImportInfo(
        source=source,
        specifiers=specifiers,
        line=call_node.start_point[0] + 1,
        kind="cjs",
    )
