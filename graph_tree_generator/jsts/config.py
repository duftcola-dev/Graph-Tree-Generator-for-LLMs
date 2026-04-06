"""Configuration schema and loader for the generic JS/TS extractor."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectConfig:
    name: str
    root: Path
    language: str  # "javascript" | "typescript" | "auto"


@dataclass
class ScanConfig:
    include: list[str]
    exclude: list[str] = field(default_factory=lambda: ["**/node_modules/**"])
    extensions: list[str] = field(default_factory=lambda: [".js", ".ts", ".tsx", ".jsx"])
    max_depth: int | None = None


@dataclass
class ExtractConfig:
    imports: bool = True
    exports: bool = True
    functions: bool = True
    calls: bool = True
    classes: bool = True
    types: bool = False


@dataclass
class ResolveConfig:
    extensions: list[str] = field(
        default_factory=lambda: [".js", ".ts", ".tsx", ".jsx", "/index.js", "/index.ts"]
    )
    tsconfig: str | None = None  # path to tsconfig.json (relative to project root)
    alias: dict[str, str] = field(default_factory=dict)
    skip_external: bool = True


@dataclass
class LabelRule:
    pattern: str  # fnmatch patterns joined by |  e.g. "router.get|router.post"
    label: str  # semantic label to apply
    capture_arg: int | None = None  # index of argument to capture as string


@dataclass
class ExtractorConfig:
    project: ProjectConfig
    scan: ScanConfig
    extract: ExtractConfig
    resolve: ResolveConfig
    labels: list[LabelRule] = field(default_factory=list)


def load_config(path: str | Path, workspace_root: Path | None = None) -> ExtractorConfig:
    """Load and validate a JSON config file."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    base = workspace_root or path.parent
    return _build_config(raw, base)


def load_config_from_dict(raw: dict, workspace_root: Path) -> ExtractorConfig:
    """Build an ExtractorConfig from a raw dict (used by the unified entry point)."""
    return _build_config(raw, workspace_root)


def _build_config(raw: dict, base: Path) -> ExtractorConfig:
    """Shared config builder from a raw dict and base directory."""
    raw_root = Path(raw["root"])
    project_root = raw_root if raw_root.is_absolute() else (base / raw["root"]).resolve()

    # Accept "type" as fallback for "language" (from unified config)
    language = raw.get("language", raw.get("type", "auto"))

    project = ProjectConfig(
        name=raw["name"],
        root=project_root,
        language=language,
    )

    scan_raw = raw.get("scan", {})
    scan = ScanConfig(
        include=raw.get("include", scan_raw.get("include", ["**/*.js", "**/*.ts"])),
        exclude=raw.get("exclude", scan_raw.get("exclude", ["**/node_modules/**"])),
        extensions=scan_raw.get("extensions", [".js", ".ts", ".tsx", ".jsx"]),
        max_depth=raw.get("max_depth", scan_raw.get("max_depth")),
    )

    ext_raw = raw.get("extract", {})
    extract = ExtractConfig(
        imports=ext_raw.get("imports", True),
        exports=ext_raw.get("exports", True),
        functions=ext_raw.get("functions", True),
        calls=ext_raw.get("calls", True),
        classes=ext_raw.get("classes", True),
        types=ext_raw.get("types", False),
    )

    res_raw = raw.get("resolve", {})
    resolve = ResolveConfig(
        extensions=res_raw.get("extensions", [".js", ".ts", ".tsx", ".jsx", "/index.js", "/index.ts"]),
        tsconfig=res_raw.get("tsconfig"),
        alias=res_raw.get("alias", {}),
        skip_external=res_raw.get("skip_external", True),
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
