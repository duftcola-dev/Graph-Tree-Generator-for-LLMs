"""Unified graph extractor + database pipeline.

Usage:
    uv run python main.py                                    # run all targets
    uv run python main.py --target hub4retail-db             # run specific target(s)
    uv run python main.py --no-embeddings                    # skip embedding generation
    uv run python main.py configs/custom.json                # custom config file
"""

import argparse
import json
import sys
from pathlib import Path

from graph_tree_generator.registry import load_targets, run_target
from graph_tree_generator.db.schema import create_database
from graph_tree_generator.db.loader import load_jsts_graph, load_ddl_graph
from graph_tree_generator.db.embeddings import (
    check_ollama,
    check_model,
    pull_model,
    generate_embeddings,
)


def load_config(config_path: Path) -> dict:
    """Load the full config file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_target_paths(targets: list[dict], workspace_root: Path) -> list[dict]:
    """Validate that target paths exist on disk. Returns only valid targets."""
    valid = []
    for t in targets:
        target_type = t.get("type", "").lower()
        name = t.get("name", "unknown")

        if target_type == "ddl":
            raw_path = Path(t["file"])
            file_path = raw_path if raw_path.is_absolute() else (workspace_root / t["file"]).resolve()
            if not file_path.exists():
                print(f"  SKIP {name}: DDL file not found: {file_path}")
                continue
        elif target_type in ("javascript", "typescript"):
            raw_root = Path(t["root"])
            root_path = raw_root if raw_root.is_absolute() else (workspace_root / t["root"]).resolve()
            if not root_path.exists():
                print(f"  SKIP {name}: root directory not found: {root_path}")
                continue
        else:
            print(f"  SKIP {name}: unknown type '{target_type}'")
            continue

        valid.append(t)

    return valid


def init()->bool:
    try:
        parser = argparse.ArgumentParser(description="Graph extractor + database pipeline")
        parser.add_argument(
            "config",
            nargs="?",
            default="graph_tree_generator/config/config.json",
            help="Path to config file (default: graph_tree_generator/config/config.json)",
        )
        parser.add_argument(
            "--target", "-t",
            action="append",
            dest="targets",
            help="Run only named targets (can repeat). Omit to run all.",
        )
        parser.add_argument(
            "--no-embeddings",
            action="store_true",
            help="Skip embedding generation even if Ollama is available.",
        )
        args = parser.parse_args()

        workspace_root = Path.cwd()
        config_path = Path(args.config)

        if not config_path.exists():
            print(f"Config not found: {config_path}")
            return False

        config = load_config(config_path)

        # ── 1. Ollama check ──────────────────────────────────────────
        ollama_config = config.get("ollama", {})
        ollama_url = ollama_config.get("url", "http://localhost:11434")
        ollama_model = ollama_config.get("model", "nomic-embed-text")
        do_embeddings = not args.no_embeddings

        if do_embeddings:
            print(f"Checking Ollama at {ollama_url}...")
            if check_ollama(ollama_url):
                print(f"  Ollama: OK")
                if check_model(ollama_url, ollama_model):
                    print(f"  Model '{ollama_model}': OK")
                else:
                    print(f"  Model '{ollama_model}' not found. Pulling...")
                    if pull_model(ollama_url, ollama_model):
                        print(f"  Model '{ollama_model}': pulled successfully")
                    else:
                        print(f"  Failed to pull '{ollama_model}'. Embeddings will be skipped.")
                        do_embeddings = False
            else:
                print("  Ollama not reachable. Embeddings will be skipped.")
                do_embeddings = False
        else:
            print("Embeddings: disabled via --no-embeddings")

        # ── 2. Load and validate targets ─────────────────────────────
        targets = load_targets(config_path, workspace_root)

        if args.targets:
            names = set(args.targets)
            targets = [t for t in targets if t["name"] in names]
            if not targets:
                print(f"No targets matched: {args.targets}")
                return False

        print(f"\nValidating {len(targets)} target(s)...")
        targets = validate_target_paths(targets, workspace_root)

        if not targets:
            print("No valid targets found.")
            return False

        print(f"  {len(targets)} target(s) ready")

        # ── 3. Extract graphs ────────────────────────────────────────
        graphs: list[tuple[dict, dict]] = []  # (target_config, graph_data)

        for target in targets:
            graph = run_target(target, workspace_root)
            if graph:
                graphs.append((target, graph))

        if not graphs:
            print("\nNo graphs extracted.")
            return False

        # ── 4. Create database and load graphs ───────────────────────
        db_config = config.get("database", {})
        db_path_raw = db_config.get("path", "graph/code_graph.db")
        db_path = Path(db_path_raw) if Path(db_path_raw).is_absolute() else (workspace_root / db_path_raw).resolve()

        print(f"\n{'=' * 60}")
        print(f"Database: {db_path}")
        print(f"{'=' * 60}")

        conn = create_database(db_path)

        total_nodes = 0
        total_edges = 0

        for target, graph in graphs:
            target_type = target.get("type", "").lower()
            target_name = target["name"]

            if target_type == "ddl":
                n, e = load_ddl_graph(conn, graph, target_name)
            else:
                n, e = load_jsts_graph(conn, graph, target_name, target_type)

            total_nodes += n
            total_edges += e
            print(f"  Loaded {target_name}: {n} nodes, {e} edges")

        print(f"\nTotal: {total_nodes} nodes, {total_edges} edges")

        # ── 5. Generate embeddings ───────────────────────────────────
        if do_embeddings:
            print(f"\n{'=' * 60}")
            print(f"Generating embeddings ({ollama_model})")
            print(f"{'=' * 60}")

            count = generate_embeddings(conn, ollama_url, ollama_model)
            print(f"  Embedded {count} nodes")
        else:
            print("\nEmbeddings: skipped")

        conn.close()
        print(f"\nDone. Database: {db_path}")
        return True
    except Exception as error:
        print(error)
        return False



