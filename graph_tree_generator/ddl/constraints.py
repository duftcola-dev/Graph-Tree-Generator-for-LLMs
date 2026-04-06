"""Regex-based constraint extractors for DDL (PKs, UKs, FKs, indexes)."""

from __future__ import annotations

import re


def extract_primary_keys(ddl_text: str, tables: dict):
    """Extract PRIMARY KEY constraints from ALTER TABLE statements."""
    pattern = r'ALTER TABLE ONLY public\."?(\w+)"?\s+ADD CONSTRAINT \w+ PRIMARY KEY \(([^)]+)\);'
    for match in re.finditer(pattern, ddl_text):
        table = match.group(1)
        cols = [c.strip().strip('"') for c in match.group(2).split(",")]
        if table in tables:
            tables[table]["primary_key"] = cols


def extract_unique_constraints(ddl_text: str, tables: dict):
    """Extract UNIQUE constraints from ALTER TABLE statements."""
    pattern = r'ALTER TABLE ONLY public\."?(\w+)"?\s+ADD CONSTRAINT (\w+) UNIQUE \(([^)]+)\);'
    for match in re.finditer(pattern, ddl_text):
        table = match.group(1)
        name = match.group(2)
        cols = [c.strip().strip('"') for c in match.group(3).split(",")]
        if table in tables:
            tables[table]["unique_constraints"].append({"name": name, "columns": cols})


def extract_foreign_keys(ddl_text: str, tables: dict):
    """Extract FOREIGN KEY constraints from ALTER TABLE statements."""
    pattern = (
        r'ALTER TABLE ONLY public\."?(\w+)"?\s+'
        r"ADD CONSTRAINT (\w+) FOREIGN KEY \(([^)]+)\) "
        r'REFERENCES public\."?(\w+)"?\(([^)]+)\)'
        r"([^;]*);"
    )
    for match in re.finditer(pattern, ddl_text):
        from_table = match.group(1)
        constraint_name = match.group(2)
        from_cols = [c.strip().strip('"') for c in match.group(3).split(",")]
        to_table = match.group(4)
        to_cols = [c.strip().strip('"') for c in match.group(5).split(",")]
        trailer = match.group(6)

        fk = {
            "constraint": constraint_name,
            "columns": from_cols,
            "references_table": to_table,
            "references_columns": to_cols,
        }

        on_delete = re.search(r"ON DELETE (\w+(?:\s+\w+)?)", trailer)
        on_update = re.search(r"ON UPDATE (\w+(?:\s+\w+)?)", trailer)
        if on_delete:
            fk["on_delete"] = on_delete.group(1)
        if on_update:
            fk["on_update"] = on_update.group(1)

        if from_table in tables:
            tables[from_table]["foreign_keys_out"].append(fk)
        if to_table in tables:
            tables[to_table]["referenced_by"].append({
                "constraint": constraint_name,
                "from_table": from_table,
                "from_columns": from_cols,
            })


def _extract_balanced_parens(text: str, start: int) -> str:
    """Extract content between balanced parentheses starting at position start."""
    if start >= len(text) or text[start] != '(':
        return ""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return ""


def _split_top_level(expr: str) -> list[str]:
    """Split expression on commas that are not inside parentheses."""
    parts = []
    depth = 0
    current = []
    for char in expr:
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
    return parts


def extract_indexes(ddl_text: str, tables: dict, views: dict):
    """Extract CREATE [UNIQUE] INDEX statements for tables and materialized views."""
    pattern = r"CREATE (UNIQUE )?INDEX (\w+) ON public\.\"?(\w+)\"? USING (\w+) "
    for match in re.finditer(pattern, ddl_text):
        unique = bool(match.group(1))
        name = match.group(2)
        target = match.group(3)
        method = match.group(4)

        paren_start = match.end()
        col_expr = _extract_balanced_parens(ddl_text, paren_start)
        if not col_expr:
            continue

        cols = _split_top_level(col_expr)

        index_entry = {
            "name": name,
            "columns": cols,
            "unique": unique,
            "method": method,
        }

        if target in tables:
            tables[target]["indexes"].append(index_entry)
        elif target in views:
            views[target].setdefault("indexes", []).append(index_entry)
