"""Code graph generator CLI.

Usage:
    uv run python main.py config init                            # create config.json
    uv run python main.py config add                             # add a target interactively
    uv run python main.py config list                            # list configured targets
    uv run python main.py config remove <name>                   # remove a target

    uv run python main.py scan                                   # extract graphs + build DB
    uv run python main.py mcp                                    # start MCP server
    uv run python main.py ollama-status                          # check Ollama connectivity

    uv run python main.py query search "authentication login"    # semantic search
    uv run python main.py query node "func::path::name"          # lookup a specific node
    uv run python main.py query neighbors "func::path::name"     # graph neighbors
    uv run python main.py query find --type function --name login # find nodes
    uv run python main.py query context "order processing"       # semantic search + graph context
    uv run python main.py query stats                            # database statistics
    uv run python main.py query tables                           # list DDL tables
    uv run python main.py query sql "SELECT ..."                 # raw SQL query
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import urllib
import click
import sqlite_vec

from graph_tree_generator.scan import init as scan_targets
from graph_tree_generator.db.embeddings import embed_text


DEFAULT_DB = "graph/code_graph.db"
DEFAULT_CONFIG = "graph_tree_generator/config/config.json"


def check_ollama() -> bool:
    """Check if Ollama is reachable."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def get_ollama_config() -> tuple[str, str]:
    config_path = Path(DEFAULT_CONFIG)
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
        ollama = cfg.get("ollama", {})
        return ollama.get("url", "http://localhost:11434"), ollama.get("model", "nomic-embed-text")
    return "http://localhost:11434", "nomic-embed-text"


def open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


# ── Root CLI group ───────────────────────────────────────────


@click.group(help="Code graph generator — scan projects, query graphs, manage config.")
def cli():
    pass


# ── Top-level commands ───────────────────────────────────────


@cli.command("scan")
def scan():
    """Extract graphs from configured targets and build the database."""
    if scan_targets():
        click.echo("Project scanning completed")
    else:
        click.echo("Project scanning failed")


@cli.command("ollama-status")
def ollama_status():
    """Check if Ollama is reachable."""
    if check_ollama():
        click.echo("Ollama is up and running")
    else:
        click.echo("Ollama not found. Install and run Ollama.")


# ── query subgroup ───────────────────────────────────────────


@cli.group(help="Query the code graph database.")
@click.option("--db", default=DEFAULT_DB, help="Path to database file.")
@click.pass_context
def query(ctx, db):
    ctx.ensure_object(dict)
    ctx.obj["conn"] = open_db(db)


@query.command()
@click.pass_context
def stats(ctx):
    """Show database statistics."""
    conn = ctx.obj["conn"]

    click.echo("=== Targets ===")
    for row in conn.execute("SELECT name, type, root FROM targets"):
        click.echo(f"  {row['name']} ({row['type']}) -> {row['root']}")

    click.echo("\n=== Node counts by type ===")
    for row in conn.execute("SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type ORDER BY cnt DESC"):
        click.echo(f"  {row['type']:25s} {row['cnt']:>6d}")

    click.echo("\n=== Edge counts by type ===")
    for row in conn.execute("SELECT type, COUNT(*) as cnt FROM edges GROUP BY type ORDER BY cnt DESC"):
        click.echo(f"  {row['type']:25s} {row['cnt']:>6d}")

    total_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    with_text = conn.execute("SELECT COUNT(*) FROM nodes WHERE source_text IS NOT NULL").fetchone()[0]
    total_emb = conn.execute("SELECT COUNT(*) FROM vec_embeddings").fetchone()[0]
    click.echo("\n=== Summary ===")
    click.echo(f"  Total nodes:      {total_nodes}")
    click.echo(f"  With source_text: {with_text}")
    click.echo(f"  With embeddings:  {total_emb}")


@query.command()
@click.argument("query_text")
@click.option("--limit", "-n", default=10, help="Max results to return.")
@click.option("--target", "-t", default=None, help="Filter to specific target.")
@click.pass_context
def search(ctx, query_text, limit, target):
    """Semantic similarity search."""
    conn = ctx.obj["conn"]
    url, model = get_ollama_config()
    vec = embed_text(url, model, query_text)
    if not vec:
        click.echo("Error: could not generate embedding. Is Ollama running?")
        return

    results = conn.execute(
        "SELECT node_id, target, distance FROM vec_embeddings WHERE embedding MATCH ? AND k = ?",
        [json.dumps(vec), limit * 3 if target else limit],
    ).fetchall()

    click.echo(f'=== Semantic search: "{query_text}" ===\n')
    shown = 0
    for r in results:
        node_id_full = r["node_id"]
        tgt = r["target"]
        if target and tgt != target:
            continue
        orig_id = node_id_full[len(tgt) + 2:]
        node = conn.execute(
            "SELECT type, name, file, line, source_text FROM nodes WHERE id = ? AND target = ?",
            (orig_id, tgt),
        ).fetchone()
        if not node:
            continue

        shown += 1
        click.echo(f"  {shown}. [{node['type']}] {node['name']}")
        click.echo(f"     file: {node['file'] or '—'}:{node['line'] or ''}")
        click.echo(f"     target: {tgt} | distance: {r['distance']:.4f}")
        if node["source_text"]:
            preview = node["source_text"][:200].replace("\n", "\n     ")
            click.echo(f"     code: {preview}...")
        click.echo()

        if shown >= limit:
            break


@query.command()
@click.argument("node_id")
@click.pass_context
def node(ctx, node_id):
    """Look up a specific node by ID (or partial match)."""
    conn = ctx.obj["conn"]

    rows = conn.execute(
        "SELECT id, target, type, name, file, line, source_text, properties FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchall()

    if not rows:
        rows = conn.execute(
            "SELECT id, target, type, name, file, line, source_text, properties FROM nodes WHERE id LIKE ?",
            (f"%{node_id}%",),
        ).fetchall()

    if not rows:
        click.echo(f"No node found matching: {node_id}")
        return

    for row in rows[:10]:
        click.echo(f"=== {row['id']} ===")
        click.echo(f"  target:     {row['target']}")
        click.echo(f"  type:       {row['type']}")
        click.echo(f"  name:       {row['name']}")
        click.echo(f"  file:       {row['file'] or '—'}:{row['line'] or ''}")
        if row["properties"]:
            props = json.loads(row["properties"])
            for k, v in props.items():
                if k == "source_text":
                    continue
                val = json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                if len(val) > 120:
                    val = val[:120] + "..."
                click.echo(f"  {k:12s} {val}")
        if row["source_text"]:
            click.echo("\n  --- source ---")
            for line in row["source_text"][:1000].split("\n"):
                click.echo(f"  {line}")
        click.echo()

    if len(rows) > 10:
        click.echo(f"  ... and {len(rows) - 10} more matches")


@query.command()
@click.argument("node_id")
@click.pass_context
def neighbors(ctx, node_id):
    """Show all edges connected to a node (in and out)."""
    conn = ctx.obj["conn"]

    exact = conn.execute("SELECT id, target FROM nodes WHERE id = ?", (node_id,)).fetchall()
    if not exact:
        exact = conn.execute(
            "SELECT id, target FROM nodes WHERE id LIKE ? LIMIT 1",
            (f"%{node_id}%",),
        ).fetchall()
    if not exact:
        click.echo(f"No node found matching: {node_id}")
        return

    nid, tgt = exact[0]["id"], exact[0]["target"]
    click.echo(f"=== Neighbors of {nid} ({tgt}) ===\n")

    out_edges = conn.execute(
        "SELECT target_node, type, properties FROM edges WHERE source = ? AND target = ?",
        (nid, tgt),
    ).fetchall()
    in_edges = conn.execute(
        "SELECT source, type, properties FROM edges WHERE target_node = ? AND target = ?",
        (nid, tgt),
    ).fetchall()

    if out_edges:
        click.echo("  Outgoing edges:")
        for e in out_edges:
            n = conn.execute(
                "SELECT type, name FROM nodes WHERE id = ? AND target = ?", (e["target_node"], tgt)
            ).fetchone()
            label = f"[{n['type']}] {n['name']}" if n else e["target_node"]
            click.echo(f"    --{e['type']}--> {label}")

    if in_edges:
        click.echo("  Incoming edges:")
        for e in in_edges:
            n = conn.execute(
                "SELECT type, name FROM nodes WHERE id = ? AND target = ?", (e["source"], tgt)
            ).fetchone()
            label = f"[{n['type']}] {n['name']}" if n else e["source"]
            click.echo(f"    <--{e['type']}-- {label}")

    if not out_edges and not in_edges:
        click.echo("  No edges found.")


@query.command()
@click.option("--type", "node_type", default=None, help="Node type (function, class, table, ...).")
@click.option("--name", default=None, help="Name pattern (supports %% wildcards).")
@click.option("--target", "-t", default=None, help="Target name.")
@click.option("--file", default=None, help="File path pattern.")
@click.option("--limit", "-n", default=20, help="Max results to return.")
@click.pass_context
def find(ctx, node_type, name, target, file, limit):
    """Find nodes by type, name, target, or file pattern."""
    conn = ctx.obj["conn"]
    conditions = []
    params = []

    if node_type:
        conditions.append("type = ?")
        params.append(node_type)
    if name:
        conditions.append("name LIKE ?")
        params.append(f"%{name}%")
    if target:
        conditions.append("target = ?")
        params.append(target)
    if file:
        conditions.append("file LIKE ?")
        params.append(f"%{file}%")

    if not conditions:
        click.echo("Provide at least one filter: --type, --name, --target, --file")
        return

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT id, target, type, name, file, line FROM nodes WHERE {where} LIMIT ?",
        params + [limit],
    ).fetchall()

    if not rows:
        click.echo("No nodes found.")
        return

    click.echo(f"=== Found {len(rows)} node(s) ===\n")
    for row in rows:
        click.echo(f"  [{row['type']}] {row['name']}")
        click.echo(f"    id: {row['id']}")
        click.echo(f"    file: {row['file'] or '—'}:{row['line'] or ''} | target: {row['target']}")
        click.echo()


@query.command()
@click.argument("query_text")
@click.option("--limit", "-n", default=5, help="Max results to return.")
@click.pass_context
def context(ctx, query_text, limit):
    """Semantic search + expand graph context around results."""
    conn = ctx.obj["conn"]
    url, model = get_ollama_config()
    vec = embed_text(url, model, query_text)
    if not vec:
        click.echo("Error: could not generate embedding. Is Ollama running?")
        return

    results = conn.execute(
        "SELECT node_id, target, distance FROM vec_embeddings WHERE embedding MATCH ? AND k = ?",
        [json.dumps(vec), limit],
    ).fetchall()

    click.echo(f'=== Context search: "{query_text}" ===\n')

    for i, r in enumerate(results, 1):
        tgt = r["target"]
        orig_id = r["node_id"][len(tgt) + 2:]
        n = conn.execute(
            "SELECT id, type, name, file, line, source_text FROM nodes WHERE id = ? AND target = ?",
            (orig_id, tgt),
        ).fetchone()
        if not n:
            continue

        click.echo(f"{'-' * 60}")
        click.echo(f"  {i}. [{n['type']}] {n['name']}  (dist={r['distance']:.4f})")
        click.echo(f"     {n['file'] or '—'}:{n['line'] or ''} | {tgt}")

        out_edges = conn.execute(
            "SELECT e.target_node, e.type, n.type as n_type, n.name as n_name "
            "FROM edges e LEFT JOIN nodes n ON n.id = e.target_node AND n.target = e.target "
            "WHERE e.source = ? AND e.target = ?",
            (n["id"], tgt),
        ).fetchall()
        in_edges = conn.execute(
            "SELECT e.source, e.type, n.type as n_type, n.name as n_name "
            "FROM edges e LEFT JOIN nodes n ON n.id = e.source AND n.target = e.target "
            "WHERE e.target_node = ? AND e.target = ?",
            (n["id"], tgt),
        ).fetchall()

        if in_edges:
            for e in in_edges[:5]:
                click.echo(f"     <-- {e['type']} -- [{e['n_type'] or '?'}] {e['n_name'] or e['source']}")
        if out_edges:
            for e in out_edges[:5]:
                click.echo(f"     --> {e['type']} --> [{e['n_type'] or '?'}] {e['n_name'] or e['target_node']}")

        if n["source_text"]:
            click.echo("\n     --- source (preview) ---")
            for line in n["source_text"][:400].split("\n"):
                click.echo(f"     {line}")

        click.echo()


@query.command()
@click.pass_context
def tables(ctx):
    """List all DDL tables with their columns."""
    conn = ctx.obj["conn"]
    rows = conn.execute(
        "SELECT name, source_text, properties FROM nodes WHERE type = 'table' ORDER BY name"
    ).fetchall()

    if not rows:
        click.echo("No tables found.")
        return

    click.echo(f"=== {len(rows)} tables ===\n")
    for row in rows:
        props = json.loads(row["properties"]) if row["properties"] else {}
        cols = props.get("columns", [])
        pk = props.get("primary_key", [])
        col_names = [c["name"] for c in cols[:8]]
        suffix = f" ... +{len(cols) - 8}" if len(cols) > 8 else ""
        pk_str = f" (PK: {', '.join(pk)})" if pk else ""
        click.echo(f"  {row['name']}{pk_str}")
        click.echo(f"    columns: {', '.join(col_names)}{suffix}")
        click.echo()


@query.command()
@click.argument("query_text")
@click.pass_context
def sql(ctx, query_text):
    """Run a raw SQL query."""
    conn = ctx.obj["conn"]
    try:
        rows = conn.execute(query_text).fetchall()
        if not rows:
            click.echo("(no results)")
            return
        keys = rows[0].keys()
        click.echo("  | ".join(keys))
        click.echo("-" * 80)
        for row in rows[:50]:
            vals = []
            for k in keys:
                v = row[k]
                s = str(v) if v is not None else "NULL"
                if len(s) > 60:
                    s = s[:60] + "..."
                vals.append(s)
            click.echo("  | ".join(vals))
        if len(rows) > 50:
            click.echo(f"\n... {len(rows) - 50} more rows")
    except Exception as e:
        click.echo(f"SQL error: {e}")


# ── config subgroup ──────────────────────────────────────────


@cli.group(help="Manage the configuration file and targets.")
def config():
    pass


def _load_config_file(config_path: Path) -> dict:
    """Load config JSON, or return a fresh skeleton if the file doesn't exist."""
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "ollama": {}, "database": {}, "targets": []}


def _save_config_file(config_path: Path, cfg: dict) -> None:
    """Write config JSON back to disk."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _prompt_ddl_target() -> dict:
    """Interactive prompts for a DDL target."""
    name = click.prompt("  Target name", type=str)
    file_path = click.prompt("  Path to DDL/SQL file", type=click.Path())

    path = Path(file_path)
    if not path.exists():
        click.echo(f"  Warning: file not found: {path.resolve()}")
        if not click.confirm("  Continue anyway?", default=False):
            raise click.Abort()

    dialect = click.prompt("  SQL dialect", default="postgres",
                           type=click.Choice(["postgres", "mysql", "sqlite", "bigquery", "tsql"],
                                             case_sensitive=False))
    output = click.prompt("  Output graph path", default=f"graph/ddl_{name}_graph.json")

    return {
        "type": "ddl",
        "name": name,
        "file": str(Path(file_path).resolve()),
        "dialect": dialect,
        "output": output,
    }


def _prompt_python_target() -> dict:
    """Interactive prompts for a Python target."""
    name = click.prompt("  Target name", type=str)
    root = click.prompt("  Project root directory", type=click.Path())

    root_path = Path(root)
    if not root_path.exists():
        click.echo(f"  Warning: directory not found: {root_path.resolve()}")
        if not click.confirm("  Continue anyway?", default=False):
            raise click.Abort()

    default_include = "**/*.py"
    default_exclude = "**/__pycache__/**, **/.venv/**, **/venv/**, **/.tox/**, **/dist/**, **/build/**, **/*.egg-info/**"

    include_raw = click.prompt("  Include patterns (comma-separated)", default=default_include)
    exclude_raw = click.prompt("  Exclude patterns (comma-separated)", default=default_exclude)

    include = [p.strip() for p in include_raw.split(",") if p.strip()]
    exclude = [p.strip() for p in exclude_raw.split(",") if p.strip()]

    output = click.prompt("  Output graph path", default=f"graph/{name}_graph.json")

    return {
        "type": "python",
        "name": name,
        "root": str(Path(root).resolve()),
        "output": output,
        "include": include,
        "exclude": exclude,
        "max_depth": 10,
        "extract": {
            "imports": True,
            "functions": True,
            "calls": True,
            "classes": True,
        },
        "resolve": {
            "skip_external": True,
            "src_roots": [],
        },
        "labels": [],
    }


def _prompt_jsts_target(lang: str) -> dict:
    """Interactive prompts for a JavaScript/TypeScript target."""
    name = click.prompt("  Target name", type=str)
    root = click.prompt("  Project root directory", type=click.Path())

    root_path = Path(root)
    if not root_path.exists():
        click.echo(f"  Warning: directory not found: {root_path.resolve()}")
        if not click.confirm("  Continue anyway?", default=False):
            raise click.Abort()

    if lang == "typescript":
        default_include = "src/**/*.ts, src/**/*.tsx"
        default_exclude = "**/node_modules/**, **/*.test.ts, **/*.test.tsx, **/*.spec.ts, **/*.spec.tsx, **/*.d.ts"
        default_extensions = ".ts, .tsx, /index.ts, /index.tsx"
    else:
        default_include = "src/**/*.js"
        default_exclude = "**/node_modules/**, **/*.test.js, **/*.spec.js"
        default_extensions = ".js, /index.js"

    include_raw = click.prompt("  Include patterns (comma-separated)", default=default_include)
    exclude_raw = click.prompt("  Exclude patterns (comma-separated)", default=default_exclude)

    include = [p.strip() for p in include_raw.split(",") if p.strip()]
    exclude = [p.strip() for p in exclude_raw.split(",") if p.strip()]

    output = click.prompt("  Output graph path", default=f"graph/{name}_graph.json")

    ext_raw = click.prompt("  Resolve extensions (comma-separated)", default=default_extensions)
    extensions = [e.strip() for e in ext_raw.split(",") if e.strip()]

    return {
        "type": lang,
        "name": name,
        "root": str(Path(root).resolve()),
        "output": output,
        "include": include,
        "exclude": exclude,
        "max_depth": 10,
        "extract": {
            "imports": True,
            "exports": True,
            "functions": True,
            "calls": True,
            "classes": lang == "javascript",
            "types": lang == "typescript",
        },
        "resolve": {
            "extensions": extensions,
            "tsconfig": None,
            "alias": {},
        },
        "labels": [],
    }


@config.command("init")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, help="Config file path.")
def config_init(config_path):
    """Create a new config.json with Ollama and database settings."""
    path = Path(config_path)

    if path.exists():
        click.echo(f"Config already exists: {path}")
        if not click.confirm("Overwrite?", default=False):
            return

    click.echo("\n=== Config setup ===\n")

    ollama_url = click.prompt("  Ollama URL", default="http://localhost:11434")
    ollama_model = click.prompt("  Embedding model", default="nomic-embed-text")
    db_path = click.prompt("  Database path", default="graph/code_graph.db")

    cfg = {
        "version": 1,
        "ollama": {"url": ollama_url, "model": ollama_model},
        "database": {"path": db_path},
        "targets": [],
    }

    if click.confirm("\n  Add a target now?", default=True):
        target_type = click.prompt(
            "  Target type",
            type=click.Choice(["ddl", "javascript", "typescript", "python"], case_sensitive=False),
        )
        if target_type == "ddl":
            target = _prompt_ddl_target()
        elif target_type == "python":
            target = _prompt_python_target()
        else:
            target = _prompt_jsts_target(target_type)
        cfg["targets"].append(target)

    _save_config_file(path, cfg)
    click.echo(f"\nConfig saved: {path}")


@config.command("add")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, help="Config file path.")
def config_add(config_path):
    """Interactively add a new target to the config."""
    path = Path(config_path)
    cfg = _load_config_file(path)

    existing_names = {t.get("name") for t in cfg.get("targets", [])}

    click.echo("\n=== Add target ===\n")

    target_type = click.prompt(
        "  Target type",
        type=click.Choice(["ddl", "javascript", "typescript", "python"], case_sensitive=False),
    )

    if target_type == "ddl":
        target = _prompt_ddl_target()
    elif target_type == "python":
        target = _prompt_python_target()
    else:
        target = _prompt_jsts_target(target_type)

    if target["name"] in existing_names:
        click.echo(f"\n  A target named '{target['name']}' already exists.")
        if not click.confirm("  Replace it?", default=False):
            return
        cfg["targets"] = [t for t in cfg["targets"] if t.get("name") != target["name"]]

    cfg["targets"].append(target)
    _save_config_file(path, cfg)
    click.echo(f"\nTarget '{target['name']}' added. ({len(cfg['targets'])} total)")


@config.command("list")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, help="Config file path.")
def config_list(config_path):
    """List all configured targets."""
    path = Path(config_path)

    if not path.exists():
        click.echo(f"Config not found: {path}")
        click.echo("Run 'config init' to create one.")
        return

    cfg = _load_config_file(path)
    targets = cfg.get("targets", [])

    if not targets:
        click.echo("No targets configured. Run 'config add' to add one.")
        return

    click.echo(f"\n=== {len(targets)} target(s) in {path} ===\n")

    for i, t in enumerate(targets, 1):
        ttype = t.get("type", "?")
        name = t.get("name", "unnamed")
        click.echo(f"  {i}. [{ttype}] {name}")

        if ttype == "ddl":
            click.echo(f"     file:    {t.get('file', '—')}")
            click.echo(f"     dialect: {t.get('dialect', 'postgres')}")
        elif ttype in ("javascript", "typescript", "python"):
            click.echo(f"     root:    {t.get('root', '—')}")
            include = t.get("include", [])
            click.echo(f"     include: {', '.join(include[:4])}")
            if len(include) > 4:
                click.echo(f"              ... +{len(include) - 4} more")

        click.echo(f"     output:  {t.get('output', '—')}")
        click.echo()


@config.command("remove")
@click.argument("name")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, help="Config file path.")
def config_remove(name, config_path):
    """Remove a target by name from the config."""
    path = Path(config_path)

    if not path.exists():
        click.echo(f"Config not found: {path}")
        return

    cfg = _load_config_file(path)
    targets = cfg.get("targets", [])
    match = [t for t in targets if t.get("name") == name]

    if not match:
        click.echo(f"No target named '{name}' found.")
        return

    if click.confirm(f"Remove target '{name}' ({match[0].get('type', '?')})?", default=False):
        cfg["targets"] = [t for t in targets if t.get("name") != name]
        _save_config_file(path, cfg)
        click.echo(f"Removed. ({len(cfg['targets'])} target(s) remaining)")


# ── Main ─────────────────────────────────────────────────────


if __name__ == "__main__":
    cli()
