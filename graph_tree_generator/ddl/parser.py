"""DDL parsing — sqlglot-based table and enum extraction."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp, ErrorLevel


def strip_public(name: str) -> str:
    """Remove public. prefix and double quotes from identifier."""
    return name.replace('"', '').removeprefix("public.")


def extract_enums(ddl_text: str) -> dict[str, list[str]]:
    """Extract CREATE TYPE ... AS ENUM via regex."""
    enums = {}
    pattern = r"CREATE TYPE public\.(\w+) AS ENUM \(\s*([\s\S]*?)\);"
    for match in re.finditer(pattern, ddl_text):
        name = match.group(1)
        values = [v.strip().strip("'") for v in match.group(2).split(",") if v.strip()]
        enums[name] = values
    return enums


def extract_tables(statements: list) -> dict:
    """Extract table definitions from sqlglot CREATE TABLE AST nodes."""
    tables = {}

    for stmt in statements:
        if not isinstance(stmt, exp.Create):
            continue
        if stmt.args.get("kind") != "TABLE":
            continue

        schema_node = stmt.find(exp.Schema)
        if not schema_node:
            continue

        table_expr = schema_node.find(exp.Table)
        if not table_expr:
            continue

        table_name = strip_public(table_expr.sql(dialect="postgres"))

        columns = []
        for col_def in schema_node.find_all(exp.ColumnDef):
            col_name = col_def.alias_or_name.replace('"', '')

            col_kind = col_def.args.get("kind")
            col_type = col_kind.sql(dialect="postgres") if col_kind else "unknown"

            nullable = True
            default = None
            generated = False

            for constraint in col_def.find_all(exp.ColumnConstraint):
                kind = constraint.args.get("kind")
                if isinstance(kind, exp.NotNullColumnConstraint):
                    nullable = False
                elif isinstance(kind, exp.DefaultColumnConstraint):
                    default = kind.this.sql(dialect="postgres") if kind.this else None
                elif hasattr(exp, "GeneratedAsIdentityColumnConstraint") and isinstance(
                    kind, exp.GeneratedAsIdentityColumnConstraint
                ):
                    generated = True
                elif hasattr(exp, "GeneratedAsRowColumnConstraint") and isinstance(
                    kind, exp.GeneratedAsRowColumnConstraint
                ):
                    generated = True

            columns.append({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "default": default,
                "generated": generated,
            })

        tables[table_name] = {
            "columns": columns,
            "primary_key": [],
            "unique_constraints": [],
            "indexes": [],
            "foreign_keys_out": [],
            "referenced_by": [],
        }

    return tables


def parse_ddl(ddl_text: str, dialect: str) -> list:
    """Parse DDL text into sqlglot AST statements."""
    return sqlglot.parse(ddl_text, dialect=dialect, error_level=ErrorLevel.WARN)
