"""Extract class definitions from Python AST."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MethodBrief:
    name: str
    async_: bool = False
    line: int = 0


MAX_SOURCE_LEN = 2000


@dataclass
class ClassInfo:
    name: str
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    methods: list[MethodBrief] = field(default_factory=list)
    line: int = 0
    source_text: str | None = None


def _text(node) -> str:
    return node.text.decode("utf-8")


def extract_classes(root_node, source: bytes) -> list[ClassInfo]:
    """Walk the AST and extract class definitions."""
    classes: list[ClassInfo] = []
    _walk_classes(root_node, classes)
    return classes


def _walk_classes(node, classes: list[ClassInfo]):
    """Recursively walk looking for class definitions."""
    if node.type == "class_definition":
        info = _extract_class(node, decorators=[])
        if info:
            classes.append(info)
        return

    if node.type == "decorated_definition":
        decorators: list[str] = []
        class_node = None
        for child in node.children:
            if child.type == "decorator":
                decorators.append(_text(child).lstrip("@").strip())
            elif child.type == "class_definition":
                class_node = child
        if class_node:
            info = _extract_class(class_node, decorators)
            if info:
                classes.append(info)
            return

    for child in node.children:
        _walk_classes(child, classes)


def _extract_class(node, decorators: list[str]) -> ClassInfo | None:
    """Parse a class_definition node."""
    name_node = node.child_by_field_name("name")
    if not name_node:
        return None

    # Extract base classes
    bases: list[str] = []
    superclasses = node.child_by_field_name("superclasses")
    if superclasses:
        for child in superclasses.children:
            if child.type in ("identifier", "attribute"):
                bases.append(_text(child))
            elif child.type == "keyword_argument":
                # metaclass=ABCMeta etc.
                bases.append(_text(child))

    # Extract method briefs from class body
    methods: list[MethodBrief] = []
    body = node.child_by_field_name("body")
    if body:
        for member in body.children:
            func_node = member
            if member.type == "decorated_definition":
                for child in member.children:
                    if child.type == "function_definition":
                        func_node = child
                        break
                else:
                    continue
            if func_node.type == "function_definition":
                m_name = func_node.child_by_field_name("name")
                if m_name:
                    is_async = any(
                        _text(c) == "async"
                        for c in func_node.children
                        if c.type not in ("block", "parameters")
                    )
                    methods.append(MethodBrief(
                        name=_text(m_name),
                        async_=is_async,
                        line=func_node.start_point[0] + 1,
                    ))

    return ClassInfo(
        name=_text(name_node),
        bases=bases,
        decorators=decorators,
        methods=methods,
        line=node.start_point[0] + 1,
        source_text=node.text.decode("utf-8")[:MAX_SOURCE_LEN],
    )
