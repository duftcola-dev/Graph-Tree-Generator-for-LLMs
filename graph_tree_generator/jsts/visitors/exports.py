"""Extract ESM exports and CommonJS module.exports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExportInfo:
    name: str  # exported binding name ("default" for default exports)
    kind: str  # "function" | "class" | "variable" | "re-export" | "unknown"
    value_hint: str | None = None  # preview of RHS (e.g. "new ClassName()")
    line: int = 0
    export_type: str = "esm"  # "esm" | "cjs"


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 80) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s


def extract_exports(root_node, source: bytes) -> list[ExportInfo]:
    """Walk the AST and extract all export declarations."""
    exports: list[ExportInfo] = []
    _walk_exports(root_node, exports)
    return exports


def _walk_exports(node, exports: list[ExportInfo]):
    """Recursively walk looking for export patterns."""
    # ESM: export ...
    if node.type == "export_statement":
        _extract_esm_export(node, exports)
        return

    # CJS: module.exports = ... or module.exports.X = ...
    if node.type == "expression_statement":
        expr = node.children[0] if node.children else None
        if expr and expr.type == "assignment_expression":
            left = expr.child_by_field_name("left")
            right = expr.child_by_field_name("right")
            if left and _is_module_exports(left):
                _extract_cjs_export(left, right, exports, node.start_point[0] + 1)
                return

    for child in node.children:
        _walk_exports(child, exports)


def _is_module_exports(node) -> bool:
    """Check if node is `module.exports` or `module.exports.X` or `exports.X`."""
    text = _text(node)
    return (
        text.startswith("module.exports")
        or text.startswith("exports.")
        and not text.startswith("exports =")
    )


def _extract_esm_export(node, exports: list[ExportInfo]):
    """Parse ESM export statement."""
    for child in node.children:
        # export default ...
        if child.type in ("function_declaration", "generator_function_declaration"):
            name_node = child.child_by_field_name("name")
            is_default = any(c.type == "default" or _text(c) == "default" for c in node.children if hasattr(c, 'type'))
            exports.append(ExportInfo(
                name=_text(name_node) if name_node else "default",
                kind="function",
                line=node.start_point[0] + 1,
            ))
            return

        if child.type == "class_declaration":
            name_node = child.child_by_field_name("name")
            exports.append(ExportInfo(
                name=_text(name_node) if name_node else "default",
                kind="class",
                line=node.start_point[0] + 1,
            ))
            return

        if child.type == "lexical_declaration":
            for decl in child.children:
                if decl.type == "variable_declarator":
                    name_node = decl.child_by_field_name("name")
                    value_node = decl.child_by_field_name("value")
                    kind = "function" if value_node and value_node.type == "arrow_function" else "variable"
                    exports.append(ExportInfo(
                        name=_text(name_node) if name_node else "anonymous",
                        kind=kind,
                        value_hint=_truncate(_text(value_node)) if value_node else None,
                        line=node.start_point[0] + 1,
                    ))
            return

        # export { X, Y, Z }
        if child.type == "export_clause":
            for spec in child.children:
                if spec.type == "export_specifier":
                    name_node = spec.child_by_field_name("name")
                    alias_node = spec.child_by_field_name("alias")
                    exports.append(ExportInfo(
                        name=_text(alias_node or name_node) if (alias_node or name_node) else "unknown",
                        kind="variable",
                        line=node.start_point[0] + 1,
                    ))
            return

        # export default <expression>
        if _text(child) == "default":
            # Next sibling is the expression
            continue

    # Fallback: check for default export of expression
    has_default = any(_text(c) == "default" for c in node.children if c.type not in ("export_clause",))
    if has_default:
        # Find the expression being exported
        for child in node.children:
            if child.type not in ("export", "default", "comment") and _text(child) != "default" and _text(child) != "export":
                exports.append(ExportInfo(
                    name="default",
                    kind="unknown",
                    value_hint=_truncate(_text(child)),
                    line=node.start_point[0] + 1,
                ))
                return


def _extract_cjs_export(left_node, right_node, exports: list[ExportInfo], line: int):
    """Parse module.exports = ... or module.exports.X = ..."""
    left_text = _text(left_node)
    right_text = _truncate(_text(right_node)) if right_node else None

    # Determine the export name
    if left_text == "module.exports":
        name = "default"
    elif left_text.startswith("module.exports."):
        name = left_text.removeprefix("module.exports.")
    elif left_text.startswith("exports."):
        name = left_text.removeprefix("exports.")
    else:
        name = "default"

    # Determine the kind from the right-hand side
    kind = "unknown"
    if right_node:
        if right_node.type == "function_expression":
            kind = "function"
        elif right_node.type == "arrow_function":
            kind = "function"
        elif right_node.type == "class_expression":
            kind = "class"
        elif right_node.type == "new_expression":
            kind = "class_instance"
        elif right_node.type == "identifier":
            kind = "variable"
        elif right_node.type == "object":
            kind = "object"

    exports.append(ExportInfo(
        name=name,
        kind=kind,
        value_hint=right_text,
        line=line,
        export_type="cjs",
    ))
