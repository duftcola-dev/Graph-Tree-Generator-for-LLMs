"""Extractor registry — loads config and dispatches to the right extractor."""

from __future__ import annotations

import json
from pathlib import Path


def load_targets(config_path: Path, workspace_root: Path) -> list[dict]:
    """Load and normalize targets from a config file.

    Handles both:
    - Global config: {"version": 1, "targets": [...]}
    - Single-target config: {"name": "...", "root": "...", ...} (legacy format)
    """
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if "targets" in raw:
        return raw["targets"]

    # Legacy single-target: infer type from existing fields
    if "file" in raw and "dialect" in raw:
        raw.setdefault("type", "ddl")
    elif "language" in raw:
        raw.setdefault("type", raw["language"])
    elif "root" in raw:
        raw.setdefault("type", "javascript")

    return [raw]


def run_target(target: dict, workspace_root: Path) -> dict | None:
    """Dispatch a single target to the appropriate extractor. Returns graph dict."""
    target_type = target.get("type", "").lower()
    name = target.get("name", "unknown")

    print(f"\n{'=' * 60}")
    print(f"Extracting: {name} (type={target_type})")
    print(f"{'=' * 60}")

    if target_type == "ddl":
        from graph_tree_generator.ddl import run_ddl_extractor
        return run_ddl_extractor(target, workspace_root)

    elif target_type in ("javascript", "typescript"):
        from graph_tree_generator.jsts.runner import run_jsts_extractor
        return run_jsts_extractor(target, workspace_root)

    else:
        print(f"Unknown extractor type: {target_type}")
        return None
