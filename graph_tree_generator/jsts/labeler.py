"""Apply semantic label rules to call expressions."""

from __future__ import annotations

import fnmatch

from .config import LabelRule
from .visitors.calls import CallInfo


def apply_labels(calls: list[CallInfo], rules: list[LabelRule]):
    """Match each call's callee chain against label rules.

    Mutates CallInfo in place, adding labels and optionally capturing arguments.
    """
    # Pre-split patterns for efficiency
    compiled: list[tuple[list[str], LabelRule]] = []
    for rule in rules:
        patterns = [p.strip() for p in rule.pattern.split("|")]
        compiled.append((patterns, rule))

    for call in calls:
        for patterns, rule in compiled:
            for pattern in patterns:
                if fnmatch.fnmatch(call.callee, pattern):
                    call.labels.append(rule.label)
                    # Capture argument if configured
                    if rule.capture_arg is not None and rule.capture_arg < len(call.args_preview):
                        raw = call.args_preview[rule.capture_arg]
                        # Strip quotes from string literals
                        call.captured_arg = raw.strip("'\"`")
                    break  # one match per rule is enough
