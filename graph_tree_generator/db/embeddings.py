"""Generate embeddings via Ollama and store in sqlite-vec."""

from __future__ import annotations

import json
import sqlite3
import urllib.request
import urllib.error


def check_ollama(base_url: str) -> bool:
    """Check if Ollama is reachable."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def check_model(base_url: str, model: str) -> bool:
    """Check if the specified model is available in Ollama."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            model_names = [m["name"] for m in data.get("models", [])]
            # Match with or without :latest tag
            return model in model_names or f"{model}:latest" in model_names
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return False


def pull_model(base_url: str, model: str) -> bool:
    """Pull a model from Ollama registry."""
    try:
        payload = json.dumps({"name": model, "stream": False}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def embed_text(base_url: str, model: str, text: str) -> list[float] | None:
    """Generate an embedding vector for a text string."""
    try:
        payload = json.dumps({"model": model, "input": text}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["embeddings"][0]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError, IndexError):
        return None


def embed_batch(base_url: str, model: str, texts: list[str]) -> list[list[float]] | None:
    """Generate embeddings for a batch of texts."""
    try:
        payload = json.dumps({"model": model, "input": texts}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data["embeddings"]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return None


def generate_embeddings(
    conn: sqlite3.Connection,
    base_url: str,
    model: str,
    batch_size: int = 32,
) -> int:
    """Generate embeddings for all nodes that have source_text."""
    cursor = conn.execute(
        "SELECT id, target, source_text FROM nodes WHERE source_text IS NOT NULL AND source_text != ''"
    )
    rows = cursor.fetchall()

    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [row[2] for row in batch]

        vectors = embed_batch(base_url, model, texts)
        if vectors is None:
            print(f"  Warning: embedding batch {i // batch_size + 1} failed, skipping")
            continue

        insert_rows = []
        for (node_id, target, _), vector in zip(batch, vectors):
            # Composite key: target::node_id to avoid cross-target collisions
            vec_key = f"{target}::{node_id}"
            insert_rows.append((vec_key, target, json.dumps(vector)))

        conn.executemany(
            "INSERT INTO vec_embeddings (node_id, target, embedding) VALUES (?, ?, ?)",
            insert_rows,
        )
        total += len(insert_rows)

        if (i // batch_size + 1) % 10 == 0:
            print(f"  Embedded {total}/{len(rows)} nodes...")

    conn.commit()
    return total
