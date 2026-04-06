"""SQLite schema creation for the code graph database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS targets (
    name        TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    root        TEXT,
    extracted_at TEXT NOT NULL,
    metadata    TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT NOT NULL,
    target      TEXT NOT NULL REFERENCES targets(name),
    type        TEXT NOT NULL,
    file        TEXT,
    line        INTEGER,
    name        TEXT,
    source_text TEXT,
    properties  TEXT,
    PRIMARY KEY (id, target)
);

CREATE TABLE IF NOT EXISTS edges (
    source      TEXT NOT NULL,
    target_node TEXT NOT NULL,
    type        TEXT NOT NULL,
    target      TEXT NOT NULL REFERENCES targets(name),
    properties  TEXT
);

CREATE TABLE IF NOT EXISTS cross_references (
    source_node   TEXT NOT NULL,
    source_target TEXT NOT NULL,
    target_node   TEXT NOT NULL,
    target_target TEXT NOT NULL,
    type          TEXT NOT NULL,
    confidence    REAL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type, target);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_edges_src  ON edges(source, target);
CREATE INDEX IF NOT EXISTS idx_edges_tgt  ON edges(target_node, target);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type, target);
CREATE INDEX IF NOT EXISTS idx_xref_src   ON cross_references(source_node, source_target);
CREATE INDEX IF NOT EXISTS idx_xref_tgt   ON cross_references(target_node, target_target);
"""


def create_database(db_path: Path) -> sqlite3.Connection:
    """Create (or recreate) the SQLite database with the full schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Full refresh: delete existing DB
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.executescript(SCHEMA_SQL)

    # sqlite-vec virtual table for embeddings
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings USING vec0(
            node_id  TEXT PRIMARY KEY,
            target   TEXT,
            embedding FLOAT[768]
        )
    """)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    return conn
