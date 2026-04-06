"""MCP server exposing code graph + embeddings as tools for Claude.

Run:
    uv run python mcp_server.py

Configure in Claude Code settings (claude_desktop_config.json or .claude/settings.json):
    {
      "mcpServers": {
        "code-graph": {
          "command": "uv",
          "args": ["run", "--directory", <absolute_path>, "python", "mcp_server.py"]
        }
      }
    }
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import sqlite_vec
from mcp.server.fastmcp import FastMCP

from graph_tree_generator.db.embeddings import embed_text

# ── Config ───────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH = PROJECT_ROOT / "graph_tree_generator" / "config" / "config.json"

def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)

_cfg = _load_config()
_ollama_url = _cfg.get("ollama", {}).get("url", "http://localhost:11434")
_ollama_model = _cfg.get("ollama", {}).get("model", "nomic-embed-text")
_db_path_raw = _cfg.get("database", {}).get("path", "graph/code_graph.db")
_db_path = Path(_db_path_raw) if Path(_db_path_raw).is_absolute() else (PROJECT_ROOT / _db_path_raw).resolve()

# ── Database connection ──────────────────────────────────────

def _get_conn() -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(str(_db_path))
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn
    except Exception as error:
        print(error)
        return None

# ── MCP Server ───────────────────────────────────────────────

mcp = FastMCP(
    "code-graph",
    instructions="""You have access to a code graph database containing structural and semantic information about a multi-target codebase.
The database contains:
- JS/TS code: functions, classes, exports, imports, calls with semantic labels (http_route, db_access, auth_check, api_call, etc.)
- DDL schema: tables, views, enums, foreign key relationships
- Vector embeddings for semantic search over source code

Workflow for answering code questions:
1. Use `search_code` to find semantically relevant code by natural language
2. Use `find_nodes` for structured lookups when you know the type/name
3. Use `get_node_detail` to read the actual source code of a node
4. Use `get_neighbors` to traverse the graph (what calls/contains/imports this?)
5. Use `trace_path` to understand how two parts of the code connect

Targets in the database represent different applications/services in the project.""",
)


@mcp.tool()
def search_code(query: str, limit: int = 10, target: str | None = None) -> str:
    """Semantic search across all code using natural language.

    Use this to find code related to a concept, feature, or behavior.
    Returns nodes ranked by semantic similarity with source code previews.

    Args:
        query: Natural language description of what you're looking for (e.g. "user authentication", "product pricing logic", "database connection setup")
        limit: Maximum number of results (default 10)
        target: Optional target filter (e.g. "<prohect_name>", "<folder_name>")
    """
    vector_text:list[float] = embed_text(_ollama_url, _ollama_model, query)
    if not vector_text:return "Error: could not generate embedding. Is Ollama running?"
    conn = _get_conn()
    if conn is None or False: return "Error: cannot connect to database"
    k = limit * 3 if target else limit
    results = conn.execute(
        "SELECT node_id, target, distance FROM vec_embeddings WHERE embedding MATCH ? AND k = ?",
        [json.dumps(vector_text), k],
    ).fetchall()

    output = []
    shown = 0
    for r in results:
        tgt = r["target"]
        if target and tgt != target:
            continue
        orig_id = r["node_id"][len(tgt) + 2:]
        node = conn.execute(
            "SELECT type, name, file, line, source_text FROM nodes WHERE id = ? AND target = ?",
            (orig_id, tgt),
        ).fetchone()
        if not node:
            continue

        shown += 1
        entry = {
            "node_id": orig_id,
            "target": tgt,
            "type": node["type"],
            "name": node["name"],
            "file": node["file"],
            "line": node["line"],
            "distance": round(r["distance"], 4),
        }
        if node["source_text"]:
            entry["source_preview"] = node["source_text"][:500]
        output.append(entry)
        if shown >= limit:
            break

    conn.close()
    return json.dumps(output, indent=2)


@mcp.tool()
def find_nodes(
    type: str | None = None,
    name: str | None = None,
    target: str | None = None,
    file: str | None = None,
    label: str | None = None,
    limit: int = 20,
) -> str:
    """Find nodes by structured filters (type, name, file, label).

    Use this when you know what kind of node you're looking for.

    Args:
        type: Node type: function, class, export, call, file, table, view, interface, type_alias, enum
        name: Name pattern (use %% as wildcard, e.g. "%%auth%%")
        target: Target name (e.g. "hub4retail-backend")
        file: File path pattern (use %% as wildcard, e.g. "%%router%%")
        label: Semantic label to filter calls (e.g. "http_route", "db_access", "api_call", "auth_check")
        limit: Max results (default 20)
    """
    conn = _get_conn()
    conditions = []
    params: list = []

    if type:
        conditions.append("n.type = ?")
        params.append(type)
    if name:
        conditions.append("n.name LIKE ?")
        params.append(f"%{name}%" if "%" not in name else name)
    if target:
        conditions.append("n.target = ?")
        params.append(target)
    if file:
        conditions.append("n.file LIKE ?")
        params.append(f"%{file}%" if "%" not in file else file)
    if label:
        conditions.append("n.properties LIKE ?")
        params.append(f'%"{label}"%')

    if not conditions:
        conn.close()
        return "Error: provide at least one filter (type, name, target, file, or label)"

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT n.id, n.target, n.type, n.name, n.file, n.line, n.properties FROM nodes n WHERE {where} LIMIT ?",
        params + [limit],
    ).fetchall()

    output = []
    for row in rows:
        entry = {
            "node_id": row["id"],
            "target": row["target"],
            "type": row["type"],
            "name": row["name"],
            "file": row["file"],
            "line": row["line"],
        }
        if row["properties"]:
            props = json.loads(row["properties"])
            if "labels" in props:
                entry["labels"] = props["labels"]
            if "captured_arg" in props:
                entry["captured_arg"] = props["captured_arg"]
            if "params" in props:
                entry["params"] = props["params"]
            if "kind" in props:
                entry["kind"] = props["kind"]
        output.append(entry)

    conn.close()
    return json.dumps(output, indent=2)


@mcp.tool()
def get_node_detail(node_id: str, target: str | None = None) -> str:
    """Get full details of a node including source code text.

    Use this to read the actual source code of a function, class, type, or table definition.

    Args:
        node_id: Full node ID (e.g. "func::path/to/file.js::functionName") or partial match
        target: Target name to disambiguate if the same node_id exists in multiple targets
    """
    conn = _get_conn()

    if target:
        rows = conn.execute(
            "SELECT id, target, type, name, file, line, source_text, properties FROM nodes WHERE id = ? AND target = ?",
            (node_id, target),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, target, type, name, file, line, source_text, properties FROM nodes WHERE id = ?",
            (node_id,),
        ).fetchall()

    # Fallback to LIKE search
    if not rows:
        like_param = f"%{node_id}%"
        if target:
            rows = conn.execute(
                "SELECT id, target, type, name, file, line, source_text, properties FROM nodes WHERE id LIKE ? AND target = ? LIMIT 5",
                (like_param, target),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, target, type, name, file, line, source_text, properties FROM nodes WHERE id LIKE ? LIMIT 5",
                (like_param,),
            ).fetchall()

    if not rows:
        conn.close()
        return f"No node found matching: {node_id}"

    output = []
    for row in rows:
        entry = {
            "node_id": row["id"],
            "target": row["target"],
            "type": row["type"],
            "name": row["name"],
            "file": row["file"],
            "line": row["line"],
        }
        if row["properties"]:
            entry["properties"] = json.loads(row["properties"])
        if row["source_text"]:
            entry["source_text"] = row["source_text"]
        output.append(entry)

    conn.close()
    return json.dumps(output, indent=2)


@mcp.tool()
def get_neighbors(node_id: str, target: str | None = None, direction: str = "both", edge_type: str | None = None) -> str:
    """Get graph neighbors of a node — follow edges in, out, or both directions.

    Use this to understand structural relationships:
    - What does this function call? (outgoing 'contains' or call edges)
    - What file contains this function? (incoming 'contains' edge)
    - What imports this file? (incoming 'imports' edges)
    - What tables does this view depend on? (outgoing 'depends_on' edges)
    - What tables reference this table via FK? (incoming 'fk' edges)

    Args:
        node_id: Full or partial node ID
        target: Target name to disambiguate
        direction: "out" (outgoing), "in" (incoming), or "both" (default)
        edge_type: Filter by edge type: imports, exports, contains, fk, depends_on, extends
    """
    conn = _get_conn()

    # Resolve node
    if target:
        exact = conn.execute("SELECT id, target FROM nodes WHERE id = ? AND target = ?", (node_id, target)).fetchone()
    else:
        exact = conn.execute("SELECT id, target FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if not exact:
        row = conn.execute("SELECT id, target FROM nodes WHERE id LIKE ? LIMIT 1", (f"%{node_id}%",)).fetchone()
        if not row:
            conn.close()
            return f"No node found matching: {node_id}"
        exact = row

    nid, tgt = exact["id"], exact["target"]
    result = {"node_id": nid, "target": tgt, "outgoing": [], "incoming": []}

    if direction in ("out", "both"):
        query = "SELECT e.target_node, e.type, e.properties, n.type as n_type, n.name as n_name, n.file as n_file, n.line as n_line FROM edges e LEFT JOIN nodes n ON n.id = e.target_node AND n.target = e.target WHERE e.source = ? AND e.target = ?"
        params = [nid, tgt]
        if edge_type:
            query += " AND e.type = ?"
            params.append(edge_type)
        for row in conn.execute(query, params).fetchall():
            entry = {
                "node_id": row["target_node"],
                "edge_type": row["type"],
                "node_type": row["n_type"],
                "name": row["n_name"],
                "file": row["n_file"],
                "line": row["n_line"],
            }
            if row["properties"]:
                entry["edge_properties"] = json.loads(row["properties"])
            result["outgoing"].append(entry)

    if direction in ("in", "both"):
        query = "SELECT e.source, e.type, e.properties, n.type as n_type, n.name as n_name, n.file as n_file, n.line as n_line FROM edges e LEFT JOIN nodes n ON n.id = e.source AND n.target = e.target WHERE e.target_node = ? AND e.target = ?"
        params = [nid, tgt]
        if edge_type:
            query += " AND e.type = ?"
            params.append(edge_type)
        for row in conn.execute(query, params).fetchall():
            entry = {
                "node_id": row["source"],
                "edge_type": row["type"],
                "node_type": row["n_type"],
                "name": row["n_name"],
                "file": row["n_file"],
                "line": row["n_line"],
            }
            if row["properties"]:
                entry["edge_properties"] = json.loads(row["properties"])
            result["incoming"].append(entry)

    conn.close()
    return json.dumps(result, indent=2)


@mcp.tool()
def trace_path(from_node: str, to_node: str, from_target: str | None = None, to_target: str | None = None, max_depth: int = 3) -> str:
    """Find how two nodes connect through the graph (up to max_depth hops).

    Use this to understand the dependency chain between two pieces of code,
    e.g. how a frontend API call connects to a backend route, or how a
    function relates to a database table.

    Args:
        from_node: Starting node ID (full or partial)
        to_node: Destination node ID (full or partial)
        from_target: Target for from_node
        to_target: Target for to_node
        max_depth: Maximum traversal depth (default 3, max 5)
    """
    conn = _get_conn()
    max_depth = min(max_depth, 5)

    # Resolve both nodes
    def resolve(nid, tgt):
        if tgt:
            row = conn.execute("SELECT id, target FROM nodes WHERE id = ? AND target = ?", (nid, tgt)).fetchone()
        else:
            row = conn.execute("SELECT id, target FROM nodes WHERE id = ?", (nid,)).fetchone()
        if not row:
            row = conn.execute("SELECT id, target FROM nodes WHERE id LIKE ? LIMIT 1", (f"%{nid}%",)).fetchone()
        return (row["id"], row["target"]) if row else (None, None)

    start_id, start_tgt = resolve(from_node, from_target)
    end_id, end_tgt = resolve(to_node, to_target)

    if not start_id:
        conn.close()
        return f"Could not find from_node: {from_node}"
    if not end_id:
        conn.close()
        return f"Could not find to_node: {to_node}"

    # BFS from start
    visited = {(start_id, start_tgt)}
    queue = [[(start_id, start_tgt, None, None)]]  # list of paths, each path is [(node_id, target, edge_type, direction)]

    for depth in range(max_depth):
        next_queue = []
        for path in queue:
            current_id, current_tgt, _, _ = path[-1]

            # Outgoing edges
            for row in conn.execute(
                "SELECT target_node, type FROM edges WHERE source = ? AND target = ?",
                (current_id, current_tgt),
            ):
                key = (row["target_node"], current_tgt)
                if key not in visited:
                    visited.add(key)
                    new_path = path + [(row["target_node"], current_tgt, row["type"], "->")]
                    if row["target_node"] == end_id:
                        # Found path
                        result = _format_path(conn, new_path)
                        conn.close()
                        return json.dumps(result, indent=2)
                    next_queue.append(new_path)

            # Incoming edges
            for row in conn.execute(
                "SELECT source, type FROM edges WHERE target_node = ? AND target = ?",
                (current_id, current_tgt),
            ):
                key = (row["source"], current_tgt)
                if key not in visited:
                    visited.add(key)
                    new_path = path + [(row["source"], current_tgt, row["type"], "<-")]
                    if row["source"] == end_id:
                        result = _format_path(conn, new_path)
                        conn.close()
                        return json.dumps(result, indent=2)
                    next_queue.append(new_path)

        queue = next_queue
        if not queue:
            break

    conn.close()
    return json.dumps({
        "found": False,
        "from": from_node,
        "to": to_node,
        "message": f"No path found within {max_depth} hops. The nodes may be in different targets or not directly connected.",
    }, indent=2)


def _format_path(conn, path):
    steps = []
    for node_id, tgt, edge_type, direction in path:
        node = conn.execute(
            "SELECT type, name, file, line FROM nodes WHERE id = ? AND target = ?",
            (node_id, tgt),
        ).fetchone()
        step = {
            "node_id": node_id,
            "target": tgt,
            "type": node["type"] if node else "unknown",
            "name": node["name"] if node else node_id,
            "file": node["file"] if node else None,
        }
        if edge_type:
            step["edge"] = f"{direction} {edge_type}"
        steps.append(step)
    return {"found": True, "hops": len(steps) - 1, "path": steps}


@mcp.tool()
def get_table_schema(table_name: str) -> str:
    """Get the full DDL schema of a database table including columns, PKs, FKs, and related tables.

    Args:
        table_name: Table name (e.g. "product", "users"). Supports partial match.
    """
    conn = _get_conn()

    node_id = f"table::{table_name}"
    row = conn.execute(
        "SELECT id, name, source_text, properties FROM nodes WHERE id = ? AND type = 'table'",
        (node_id,),
    ).fetchone()

    if not row:
        # Try partial match
        rows = conn.execute(
            "SELECT id, name, source_text, properties FROM nodes WHERE type = 'table' AND name LIKE ?",
            (f"%{table_name}%",),
        ).fetchall()
        if not rows:
            conn.close()
            return f"No table found matching: {table_name}"
        if len(rows) > 1:
            names = [r["name"] for r in rows[:20]]
            conn.close()
            return json.dumps({"message": "Multiple tables match. Be more specific.", "matches": names})
        row = rows[0]

    result = {
        "table": row["name"],
        "description": row["source_text"],
    }

    if row["properties"]:
        props = json.loads(row["properties"])
        result["columns"] = props.get("columns", [])
        result["primary_key"] = props.get("primary_key", [])
        result["unique_constraints"] = props.get("unique_constraints", [])

    # FK relationships
    outgoing = conn.execute(
        "SELECT target_node, properties FROM edges WHERE source = ? AND type = 'fk'",
        (row["id"],),
    ).fetchall()
    incoming = conn.execute(
        "SELECT source, properties FROM edges WHERE target_node = ? AND type = 'fk'",
        (row["id"],),
    ).fetchall()

    if outgoing:
        result["references"] = []
        for e in outgoing:
            ref = {"table": e["target_node"].replace("table::", "")}
            if e["properties"]:
                ref.update(json.loads(e["properties"]))
            result["references"].append(ref)

    if incoming:
        result["referenced_by"] = []
        for e in incoming:
            ref = {"table": e["source"].replace("table::", "")}
            if e["properties"]:
                ref.update(json.loads(e["properties"]))
            result["referenced_by"].append(ref)

    conn.close()
    return json.dumps(result, indent=2)


@mcp.tool()
def graph_overview() -> str:
    """Get an overview of the code graph database: targets, node/edge counts, and available types.

    Call this first to understand what's in the database before querying.
    """
    conn = _get_conn()

    targets = []
    for row in conn.execute("SELECT name, type, root FROM targets"):
        targets.append({"name": row["name"], "type": row["type"], "root": row["root"]})

    node_counts = {}
    for row in conn.execute("SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type ORDER BY cnt DESC"):
        node_counts[row["type"]] = row["cnt"]

    edge_counts = {}
    for row in conn.execute("SELECT type, COUNT(*) as cnt FROM edges GROUP BY type ORDER BY cnt DESC"):
        edge_counts[row["type"]] = row["cnt"]

    total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    with_source = conn.execute("SELECT COUNT(*) FROM nodes WHERE source_text IS NOT NULL").fetchone()[0]
    with_emb = conn.execute("SELECT COUNT(*) FROM vec_embeddings").fetchone()[0]

    conn.close()
    return json.dumps({
        "targets": targets,
        "node_counts_by_type": node_counts,
        "edge_counts_by_type": edge_counts,
        "total_nodes": total,
        "nodes_with_source_text": with_source,
        "nodes_with_embeddings": with_emb,
    }, indent=2)


# ── Entry point ──────────────────────────────────────────────
def init():
    mcp.run()

