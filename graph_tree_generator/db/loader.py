"""Load graph data (JSTS and DDL) into the SQLite database."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime


def load_jsts_graph(conn: sqlite3.Connection, graph: dict, target_name: str, target_type: str):
    """Load a JS/TS graph into the database."""
    meta = graph["metadata"]

    conn.execute(
        "INSERT INTO targets (name, type, root, extracted_at, metadata) VALUES (?, ?, ?, ?, ?)",
        (target_name, target_type, meta.get("project_root", ""), meta["extracted_at"], json.dumps(meta)),
    )

    nodes = graph["nodes"]
    edges = graph["edges"]

    # Insert nodes
    node_rows = []
    for n in nodes:
        # Separate well-known fields from extras
        props = {k: v for k, v in n.items() if k not in ("id", "type", "file", "line", "name", "source_text")}
        node_rows.append((
            n["id"],
            target_name,
            n["type"],
            n.get("file"),
            n.get("line"),
            n.get("name") or n.get("callee") or n.get("path"),
            n.get("source_text"),
            json.dumps(props) if props else None,
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO nodes (id, target, type, file, line, name, source_text, properties) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        node_rows,
    )

    # Insert edges
    edge_rows = []
    for e in edges:
        if not e.get("from") or not e.get("to"):
            continue
        props = {k: v for k, v in e.items() if k not in ("from", "to", "type")}
        edge_rows.append((
            e["from"],
            e["to"],
            e["type"],
            target_name,
            json.dumps(props) if props else None,
        ))

    conn.executemany(
        "INSERT INTO edges (source, target_node, type, target, properties) VALUES (?, ?, ?, ?, ?)",
        edge_rows,
    )

    conn.commit()
    return len(node_rows), len(edge_rows)


def load_ddl_graph(conn: sqlite3.Connection, graph: dict, target_name: str):
    """Load a DDL graph into the database, normalizing into nodes/edges."""
    meta = graph["metadata"]

    conn.execute(
        "INSERT INTO targets (name, type, root, extracted_at, metadata) VALUES (?, ?, ?, ?, ?)",
        (target_name, "ddl", meta.get("source", ""), meta["extracted_at"], json.dumps(meta)),
    )

    node_rows = []
    edge_rows = []

    # Tables → nodes
    for table_name, table_data in graph.get("tables", {}).items():
        node_id = f"table::{table_name}"
        props = {
            "columns": table_data["columns"],
            "primary_key": table_data.get("primary_key", []),
            "unique_constraints": table_data.get("unique_constraints", []),
            "indexes": table_data.get("indexes", []),
        }
        node_rows.append((
            node_id,
            target_name,
            "table",
            None,
            None,
            table_name,
            table_data.get("source_text"),
            json.dumps(props),
        ))

    # Views → nodes
    for view_name, view_data in graph.get("views", {}).items():
        node_id = f"view::{view_name}"
        vtype = "materialized_view" if view_data.get("materialized") else "view"
        props = {
            "columns": view_data.get("columns", []),
            "source_tables": view_data.get("source_tables", []),
            "materialized": view_data.get("materialized", False),
        }
        node_rows.append((
            node_id,
            target_name,
            vtype,
            None,
            None,
            view_name,
            view_data.get("source_text"),
            json.dumps(props),
        ))

    # Enums → nodes
    for enum_name, enum_values in graph.get("enums", {}).items():
        node_id = f"enum::{enum_name}"
        source_text = f"Enum: {enum_name}\nValues: {', '.join(enum_values)}"
        node_rows.append((
            node_id,
            target_name,
            "enum",
            None,
            None,
            enum_name,
            source_text,
            json.dumps({"values": enum_values}),
        ))

    # FK relationships → edges
    for rel in graph.get("relationships", []):
        edge_rows.append((
            f"table::{rel['from_table']}",
            f"table::{rel['to_table']}",
            "fk",
            target_name,
            json.dumps({
                "from_columns": rel["from_columns"],
                "to_columns": rel["to_columns"],
                "constraint": rel.get("constraint"),
            }),
        ))

    # View dependencies → edges
    for dep in graph.get("view_dependencies", []):
        source_id = f"view::{dep['view']}"
        target_id = f"table::{dep['depends_on']}"
        edge_rows.append((
            source_id,
            target_id,
            "depends_on",
            target_name,
            json.dumps({"materialized": dep.get("materialized", False)}),
        ))

    conn.executemany(
        "INSERT INTO nodes (id, target, type, file, line, name, source_text, properties) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        node_rows,
    )
    conn.executemany(
        "INSERT INTO edges (source, target_node, type, target, properties) VALUES (?, ?, ?, ?, ?)",
        edge_rows,
    )

    conn.commit()
    return len(node_rows), len(edge_rows)
