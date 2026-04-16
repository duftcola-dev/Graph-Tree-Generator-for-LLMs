"""Python extractor runner — callable from the unified entry point."""

from __future__ import annotations

import json
from pathlib import Path

from .config import load_config_from_dict
from .scanner import discover_files
from .parser import extract_file
from .resolver import ImportResolver
from .labeler import apply_labels
from .graph_builder import build_graph


def run_python_extractor(target: dict, workspace_root: Path) -> dict | None:
    """Run the Python extractor for a single target. Returns graph dict."""
    config = load_config_from_dict(target, workspace_root)

    print(f"Root:    {config.project.root}")

    # Discover files
    files = discover_files(config)
    print(f"Files:   {len(files)}")

    if not files:
        print("No files found. Check include/exclude patterns.")
        return None

    # Initialize import resolver
    resolver = ImportResolver(config.project.root, config.resolve)

    # Extract each file
    results = []
    errors = []
    for f in files:
        try:
            result = extract_file(f, config.project.root, config)
            if result:
                for imp in result.imports:
                    resolved = resolver.resolve(imp.source, f)
                    imp.resolved_path = resolved

                apply_labels(result.calls, config.labels)
                results.append(result)
        except Exception as e:
            errors.append((f.relative_to(config.project.root).as_posix(), str(e)))

    # Build graph
    graph = build_graph(results, config)

    # Write output
    output_name = target.get("output", f"python_{config.project.name}_graph.json")
    if not output_name.startswith("graph/"):
        output_path = (workspace_root / "graph" / output_name).resolve()
    else:
        output_path = (workspace_root / output_name).resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    # Summary
    m = graph["metadata"]
    print(f"\n--- Results ---")
    print(f"Files:     {m['total_files']}")
    print(f"Functions: {m['total_functions']}")
    print(f"Classes:   {m['total_classes']}")
    print(f"Calls:     {m['total_calls']} ({m['total_labeled_calls']} labeled)")
    print(f"Nodes:     {m['total_nodes']}")
    print(f"Edges:     {m['total_edges']}")
    print(f"Output:    {output_path}")

    if errors:
        print(f"\nWarnings ({len(errors)} files had errors):")
        for path, err in errors[:10]:
            print(f"  {path}: {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    return graph
