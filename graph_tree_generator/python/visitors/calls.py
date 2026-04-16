"""Extract call expressions from Python AST."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallInfo:
    callee: str  # flattened callee chain e.g. "os.path.join", "self.method"
    args_preview: list[str] = field(default_factory=list)
    line: int = 0
    labels: list[str] = field(default_factory=list)  # filled in by labeler
    captured_arg: str | None = None  # filled in by labeler


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def flatten_callee(node) -> str:
    """Recursively flatten an attribute chain into 'a.b.c' string."""
    if node.type == "identifier":
        return _text(node)
    if node.type == "attribute":
        obj = node.child_by_field_name("object")
        attr = node.child_by_field_name("attribute")
        if obj and attr:
            return f"{flatten_callee(obj)}.{_text(attr)}"
    if node.type == "call":
        func = node.child_by_field_name("function")
        if func:
            return flatten_callee(func) + "()"
    if node.type == "subscript":
        value = node.child_by_field_name("value")
        if value:
            return flatten_callee(value)
    return _truncate(_text(node), 40)


def _extract_args_preview(args_node, max_args: int = 3) -> list[str]:
    """Extract string previews of the first N arguments."""
    if not args_node:
        return []
    previews = []
    count = 0
    for child in args_node.children:
        if child.type in ("(", ")", ","):
            continue
        previews.append(_truncate(_text(child)))
        count += 1
        if count >= max_args:
            break
    return previews


def extract_calls(root_node, source: bytes) -> list[CallInfo]:
    """Walk the AST and extract all call expressions."""
    calls: list[CallInfo] = []
    _walk_calls(root_node, calls)
    return calls


def _walk_calls(node, calls: list[CallInfo]):
    """Recursively walk looking for call expressions."""
    if node.type == "call":
        info = _extract_call(node)
        if info:
            calls.append(info)

    for child in node.children:
        _walk_calls(child, calls)


def _extract_call(node) -> CallInfo | None:
    """Extract a call expression."""
    func_node = node.child_by_field_name("function")
    if not func_node:
        return None

    callee = flatten_callee(func_node)

    if callee in ("", "()"):
        return None

    args_node = node.child_by_field_name("arguments")
    args_preview = _extract_args_preview(args_node)

    return CallInfo(
        callee=callee,
        args_preview=args_preview,
        line=node.start_point[0] + 1,
    )
