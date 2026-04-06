"""DDL extractor runner — orchestrates the full DDL extraction pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from .config import load_ddl_config
from .graph_builder import build_graph


def run_ddl_extractor(target: dict, workspace_root: Path) -> dict | None:
    """Run the DDL extractor for a single target. Returns graph dict."""
    config = load_ddl_config(target, workspace_root)

    ddl_text = config.file.read_text(encoding="utf-8")
    graph = build_graph(ddl_text, config.dialect, str(config.file))

    config.output.parent.mkdir(parents=True, exist_ok=True)
    with open(config.output, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    m = graph["metadata"]
    print(f"Tables:  {m['total_tables']}")
    print(f"Views:   {m['total_views']} ({m['total_materialized_views']} materialized, {m['total_regular_views']} regular)")
    print(f"Enums:   {m['total_enums']}")
    print(f"FKs:     {m['total_foreign_keys']}")
    print(f"Indexes: {m['total_indexes']}")
    print(f"Output:  {config.output}")

    return graph
