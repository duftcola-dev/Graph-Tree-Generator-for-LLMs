"""Extract Python import and from-import statements."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportSpecifier:
    name: str  # imported name (e.g. "os", "path", "MyClass")
    alias: str | None = None  # local binding if renamed via `as`


@dataclass
class ImportInfo:
    source: str  # module path (e.g. "os.path", ".utils", "..models.user")
    specifiers: list[ImportSpecifier] = field(default_factory=list)
    line: int = 0
    kind: str = "import"  # "import" | "from_import"
    resolved_path: str | None = None


def _text(node) -> str:
    return node.text.decode("utf-8")


def extract_imports(root_node, source: bytes) -> list[ImportInfo]:
    """Walk the AST and extract all import statements."""
    imports: list[ImportInfo] = []
    _walk_imports(root_node, imports)
    return imports


def _walk_imports(node, imports: list[ImportInfo]):
    """Recursively walk looking for import patterns."""
    if node.type == "import_statement":
        _extract_import(node, imports)
        return

    if node.type == "import_from_statement":
        _extract_from_import(node, imports)
        return

    for child in node.children:
        _walk_imports(child, imports)


def _extract_import(node, imports: list[ImportInfo]):
    """Parse `import X`, `import X as Y`, `import X.Y.Z`."""
    for child in node.children:
        if child.type == "dotted_name":
            module = _text(child)
            imports.append(ImportInfo(
                source=module,
                specifiers=[ImportSpecifier(name=module.split(".")[-1])],
                line=node.start_point[0] + 1,
                kind="import",
            ))
        elif child.type == "aliased_import":
            name_node = child.child_by_field_name("name")
            alias_node = child.child_by_field_name("alias")
            if name_node:
                module = _text(name_node)
                imports.append(ImportInfo(
                    source=module,
                    specifiers=[ImportSpecifier(
                        name=module.split(".")[-1],
                        alias=_text(alias_node) if alias_node else None,
                    )],
                    line=node.start_point[0] + 1,
                    kind="import",
                ))


def _extract_from_import(node, imports: list[ImportInfo]):
    """Parse `from X import Y`, `from X import Y as Z`, `from . import X`."""
    # Find the module name
    module_name = None
    for child in node.children:
        if child.type == "dotted_name":
            module_name = _text(child)
            break
        elif child.type == "relative_import":
            module_name = _text(child)
            break

    if module_name is None:
        # `from . import X` — the dots are direct children
        dots = ""
        for child in node.children:
            if _text(child) == ".":
                dots += "."
            elif child.type == "dotted_name":
                module_name = dots + _text(child)
                break
        if module_name is None and dots:
            module_name = dots

    if module_name is None:
        return

    # Extract imported names
    specifiers: list[ImportSpecifier] = []
    for child in node.children:
        if child.type == "dotted_name" and _text(child) == module_name:
            continue  # skip the module name itself
        if child.type == "dotted_name":
            specifiers.append(ImportSpecifier(name=_text(child)))
        elif child.type == "aliased_import":
            name_node = child.child_by_field_name("name")
            alias_node = child.child_by_field_name("alias")
            if name_node:
                specifiers.append(ImportSpecifier(
                    name=_text(name_node),
                    alias=_text(alias_node) if alias_node else None,
                ))
        elif child.type == "wildcard_import":
            specifiers.append(ImportSpecifier(name="*"))

    imports.append(ImportInfo(
        source=module_name,
        specifiers=specifiers,
        line=node.start_point[0] + 1,
        kind="from_import",
    ))
