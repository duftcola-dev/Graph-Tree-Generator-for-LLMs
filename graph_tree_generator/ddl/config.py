"""DDL extractor configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class DDLConfig:
    name: str
    file: Path
    dialect: str
    output: Path


def load_ddl_config(target: dict, workspace_root: Path) -> DDLConfig:
    """Build a DDLConfig from a target dict."""
    name = target.get("name", "db")
    raw_file = Path(target["file"])
    file_path = raw_file if raw_file.is_absolute() else (workspace_root / target["file"]).resolve()

    if not file_path.exists():
        raise FileNotFoundError(f"DDL file not found: {file_path}")

    dialect = target.get("dialect", "postgres")
    output = target.get("output", f"graph/ddl_{name}_graph.json")
    output_path = (workspace_root / output).resolve()

    return DDLConfig(name=name, file=file_path, dialect=dialect, output=output_path)
