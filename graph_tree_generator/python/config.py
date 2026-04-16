"""Configuration schema and loader for the Python extractor."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectConfig:
    name: str
    root: Path


@dataclass
class ScanConfig:
    include: list[str]
    exclude: list[str] = field(default_factory=lambda: ["**/__pycache__/**"])
    max_depth: int | None = None


@dataclass
class ExtractConfig:
    imports: bool = True
    functions: bool = True
    calls: bool = True
    classes: bool = True


@dataclass
class ResolveConfig:
    skip_external: bool = True
    src_roots: list[str] = field(default_factory=list)


@dataclass
class LabelRule:
    pattern: str  # fnmatch patterns joined by |
    label: str
    capture_arg: int | None = None


@dataclass
class ExtractorConfig:
    project: ProjectConfig
    scan: ScanConfig
    extract: ExtractConfig
    resolve: ResolveConfig
    labels: list[LabelRule] = field(default_factory=list)


def load_config_from_dict(raw: dict, workspace_root: Path) -> ExtractorConfig:
    """Build an ExtractorConfig from a raw dict (used by the unified entry point)."""
    raw_root = Path(raw["root"])
    project_root = raw_root if raw_root.is_absolute() else (workspace_root / raw["root"]).resolve()

    project = ProjectConfig(
        name=raw["name"],
        root=project_root,
    )

    scan_raw = raw.get("scan", {})
    scan = ScanConfig(
        include=raw.get("include", scan_raw.get("include", ["**/*.py"])),
        exclude=raw.get("exclude", scan_raw.get("exclude", [
            "**/__pycache__/**",
            "**/.venv/**",
            "**/venv/**",
            "**/.tox/**",
            "**/dist/**",
            "**/build/**",
            "**/*.egg-info/**",
        ])),
        max_depth=raw.get("max_depth", scan_raw.get("max_depth")),
    )

    ext_raw = raw.get("extract", {})
    extract = ExtractConfig(
        imports=ext_raw.get("imports", True),
        functions=ext_raw.get("functions", True),
        calls=ext_raw.get("calls", True),
        classes=ext_raw.get("classes", True),
    )

    res_raw = raw.get("resolve", {})
    resolve = ResolveConfig(
        skip_external=res_raw.get("skip_external", True),
        src_roots=res_raw.get("src_roots", []),
    )

    labels = []
    for lr in raw.get("labels", []):
        labels.append(LabelRule(
            pattern=lr["pattern"],
            label=lr["label"],
            capture_arg=lr.get("capture_arg"),
        ))

    return ExtractorConfig(
        project=project,
        scan=scan,
        extract=extract,
        resolve=resolve,
        labels=labels,
    )
