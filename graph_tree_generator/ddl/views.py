"""DDL view extraction — CREATE VIEW and CREATE MATERIALIZED VIEW."""

from __future__ import annotations

import re


def extract_views(ddl_text: str, table_names: set[str]) -> dict:
    """Extract CREATE [MATERIALIZED] VIEW definitions and their source tables."""
    views = {}

    pattern = (
        r"CREATE (MATERIALIZED )?VIEW public\.(\w+) AS\s+"
        r"([\s\S]*?);"
    )

    for match in re.finditer(pattern, ddl_text):
        materialized = bool(match.group(1))
        view_name = match.group(2)
        view_body = match.group(3)

        output_columns = _extract_view_columns(view_body)
        source_tables = _extract_source_tables(view_body, table_names, view_name)

        views[view_name] = {
            "materialized": materialized,
            "columns": output_columns,
            "source_tables": sorted(source_tables),
            "indexes": [],
        }

    return views


def _extract_view_columns(view_body: str) -> list[dict]:
    """Extract column aliases from the outermost SELECT clause."""
    columns = []

    body = view_body
    if re.match(r"\s*WITH\s+", body, re.IGNORECASE):
        depth = 0
        main_select_pos = 0
        i = 0
        while i < len(body):
            if body[i] == '(':
                depth += 1
            elif body[i] == ')':
                depth -= 1
            elif depth == 0 and body[i:i+6].upper() == 'SELECT':
                main_select_pos = i
            i += 1
        body = body[main_select_pos:]

    select_match = re.search(
        r"SELECT\s+([\s\S]*?)\s+FROM\s+",
        body,
        re.IGNORECASE,
    )
    if not select_match:
        return columns

    select_clause = select_match.group(1)

    depth = 0
    current = []
    parts = []
    for char in select_clause:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif char == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        parts.append(''.join(current).strip())

    for part in parts:
        as_match = re.search(r'\bAS\s+"?(\w+)"?\s*$', part, re.IGNORECASE)
        if as_match:
            columns.append({"name": as_match.group(1)})
        else:
            ident_match = re.search(r'\.?"?(\w+)"?\s*$', part)
            if ident_match:
                columns.append({"name": ident_match.group(1)})

    return columns


def _extract_source_tables(view_body: str, table_names: set[str], view_name: str) -> set[str]:
    """Extract all table/view names referenced in FROM/JOIN clauses."""
    refs = set(re.findall(r"public\.(\w+)", view_body))
    refs.discard(view_name)
    return refs & table_names
