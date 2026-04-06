"""Extract call expressions with callee chain flattening."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallInfo:
    callee: str  # flattened callee chain e.g. "router.post", "connectorHandler.connector.find_items"
    args_preview: list[str] = field(default_factory=list)  # first few args as string previews
    line: int = 0
    is_new: bool = False  # true for `new X()` expressions
    labels: list[str] = field(default_factory=list)  # filled in by labeler
    captured_arg: str | None = None  # filled in by labeler


def _text(node) -> str:
    return node.text.decode("utf-8")


def _truncate(s: str, max_len: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:max_len] + "..." if len(s) > max_len else s


def flatten_callee(node) -> str:
    """Recursively flatten a member_expression chain into 'a.b.c' string."""
    if node.type == "identifier":
        return _text(node)
    if node.type == "this":
        return "this"
    if node.type == "member_expression":
        obj = node.child_by_field_name("object")
        prop = node.child_by_field_name("property")
        if obj and prop:
            return f"{flatten_callee(obj)}.{_text(prop)}"
    if node.type == "subscript_expression":
        obj = node.child_by_field_name("object")
        if obj:
            return flatten_callee(obj)
    if node.type == "call_expression":
        # Chained calls: foo()() or foo().bar()
        func = node.child_by_field_name("function")
        if func:
            return flatten_callee(func) + "()"
    # Fallback: return raw text (truncated)
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
    """Recursively walk looking for call and new expressions."""
    if node.type == "call_expression":
        info = _extract_call(node, is_new=False)
        if info:
            calls.append(info)

    elif node.type == "new_expression":
        info = _extract_call(node, is_new=True)
        if info:
            calls.append(info)

    for child in node.children:
        _walk_calls(child, calls)


def _extract_call(node, is_new: bool) -> CallInfo | None:
    """Extract a call_expression or new_expression."""
    func_node = node.child_by_field_name("function")
    if not func_node:
        # new_expression uses "constructor" field
        func_node = node.child_by_field_name("constructor")
    if not func_node:
        return None

    callee = flatten_callee(func_node)

    # Skip very short/uninteresting calls
    if callee in ("", "()"):
        return None

    args_node = node.child_by_field_name("arguments")
    args_preview = _extract_args_preview(args_node)

    return CallInfo(
        callee=callee,
        args_preview=args_preview,
        line=node.start_point[0] + 1,
        is_new=is_new,
    )
