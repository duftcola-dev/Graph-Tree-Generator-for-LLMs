"""Assemble the complete DDL graph from extracted components."""

from __future__ import annotations

import re
from datetime import datetime

from .parser import parse_ddl, extract_tables, extract_enums
from .constraints import (
    extract_primary_keys,
    extract_unique_constraints,
    extract_foreign_keys,
    extract_indexes,
)
from .views import extract_views


def _table_source_text(name: str, table: dict) -> str:
    """Generate a structured text description of a table for embeddings."""
    lines = [f"Table: {name}"]
    lines.append("Columns:")
    for col in table["columns"]:
        parts = [f"  - {col['name']}: {col['type']}"]
        if not col["nullable"]:
            parts.append("NOT NULL")
        if col["default"]:
            parts.append(f"DEFAULT {col['default']}")
        if col["generated"]:
            parts.append("GENERATED")
        lines.append(" ".join(parts))
    if table["primary_key"]:
        lines.append(f"Primary key: {', '.join(table['primary_key'])}")
    for fk in table["foreign_keys_out"]:
        lines.append(
            f"FK: {', '.join(fk['columns'])} -> {fk['references_table']}({', '.join(fk['references_columns'])})"
        )
    for uc in table["unique_constraints"]:
        lines.append(f"Unique: {', '.join(uc['columns'])}")
    return "\n".join(lines)


def _view_source_text(name: str, view: dict) -> str:
    """Generate a structured text description of a view for embeddings."""
    kind = "Materialized view" if view["materialized"] else "View"
    lines = [f"{kind}: {name}"]
    if view.get("columns"):
        lines.append("Columns:")
        for col in view["columns"]:
            lines.append(f"  - {col['name']}: {col.get('type', 'unknown')}")
    if view.get("source_tables"):
        lines.append(f"Sources: {', '.join(view['source_tables'])}")
    if view.get("definition"):
        defn = view["definition"][:500]
        lines.append(f"Definition: {defn}")
    return "\n".join(lines)


def build_graph(ddl_text: str, dialect: str, source_path: str) -> dict:
    """Build the complete database graph from DDL text."""
    # Phase 1a: sqlglot AST for CREATE TABLE (column definitions)
    statements = parse_ddl(ddl_text, dialect)
    tables = extract_tables(statements)

    # Phase 1b: regex for constraints and enums
    enums = extract_enums(ddl_text)
    extract_primary_keys(ddl_text, tables)
    extract_unique_constraints(ddl_text, tables)
    extract_foreign_keys(ddl_text, tables)

    # Phase 1c: views (need all known names to resolve source references)
    view_name_pattern = r"CREATE (?:MATERIALIZED )?VIEW public\.(\w+) AS"
    all_known_names = set(tables.keys()) | set(re.findall(view_name_pattern, ddl_text))
    views = extract_views(ddl_text, all_known_names)

    # Phase 1d: indexes (for both tables and materialized views)
    extract_indexes(ddl_text, tables, views)

    # Phase 2: generate source_text for embeddings
    for table_name, table_data in tables.items():
        table_data["source_text"] = _table_source_text(table_name, table_data)
    for view_name, view_data in views.items():
        view_data["source_text"] = _view_source_text(view_name, view_data)

    # Flat FK relationship list for graph traversal
    relationships = []
    for table_name, table_data in tables.items():
        for fk in table_data["foreign_keys_out"]:
            relationships.append({
                "from_table": table_name,
                "from_columns": fk["columns"],
                "to_table": fk["references_table"],
                "to_columns": fk["references_columns"],
                "constraint": fk["constraint"],
            })

    # View-to-table dependency edges
    view_dependencies = []
    for view_name, view_data in views.items():
        for source_table in view_data["source_tables"]:
            view_dependencies.append({
                "view": view_name,
                "depends_on": source_table,
                "materialized": view_data["materialized"],
            })

    mat_count = sum(1 for v in views.values() if v["materialized"])
    reg_count = len(views) - mat_count
    total_indexes = (
        sum(len(t["indexes"]) for t in tables.values())
        + sum(len(v["indexes"]) for v in views.values())
    )

    return {
        "metadata": {
            "extracted_at": datetime.now().isoformat(),
            "source": source_path,
            "total_tables": len(tables),
            "total_views": len(views),
            "total_materialized_views": mat_count,
            "total_regular_views": reg_count,
            "total_enums": len(enums),
            "total_foreign_keys": len(relationships),
            "total_indexes": total_indexes,
        },
        "enums": enums,
        "tables": tables,
        "views": views,
        "relationships": relationships,
        "view_dependencies": view_dependencies,
    }
