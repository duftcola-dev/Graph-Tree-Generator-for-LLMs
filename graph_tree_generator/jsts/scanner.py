"""File discovery with glob include/exclude and max_depth."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .config import ExtractorConfig


def discover_files(config: ExtractorConfig) -> list[Path]:
    """Walk project root, apply include/exclude globs, return sorted file list."""
    root = config.project.root

    if not root.exists():
        raise FileNotFoundError(f"Project root not found: {root}")

    # Collect all files matching include patterns
    candidates: set[Path] = set()
    for pattern in config.scan.include:
        for match in root.glob(pattern):
            if match.is_file():
                candidates.add(match)

    # Filter by max_depth
    if config.scan.max_depth is not None:
        max_depth = config.scan.max_depth
        filtered = set()
        for f in candidates:
            try:
                rel = f.relative_to(root)
                if len(rel.parts) <= max_depth:
                    filtered.add(f)
            except ValueError:
                continue
        candidates = filtered

    # Filter by exclude patterns
    result = []
    for f in candidates:
        rel_str = f.relative_to(root).as_posix()
        excluded = False
        for pattern in config.scan.exclude:
            if fnmatch.fnmatch(rel_str, pattern):
                excluded = True
                break
        if not excluded:
            result.append(f)

    return sorted(result)
