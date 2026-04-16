"""Assemble FileResults into a nodes + edges JSON graph."""

from __future__ import annotations

from datetime import datetime

from .config import ExtractorConfig
from .parser import FileResult


def build_graph(file_results: list[FileResult], config: ExtractorConfig) -> dict:
    """Build the complete graph from all file extraction results."""
    nodes: list[dict] = []
    edges: list[dict] = []

    for fr in file_results:
        # File node
        file_id = f"file::{fr.path}"
        nodes.append({
            "id": file_id,
            "type": "file",
            "path": fr.path,
        })

        # Import edges
        for imp in fr.imports:
            edge = {
                "from": file_id,
                "to": f"file::{imp.resolved_path}" if imp.resolved_path else None,
                "type": "imports",
                "specifier": imp.source,
                "bindings": [
                    {"name": s.name, "alias": s.alias}
                    for s in imp.specifiers
                ],
                "line": imp.line,
                "kind": imp.kind,
            }
            edges.append(edge)

        # Function nodes
        for func in fr.functions:
            qual_name = f"{func.enclosing_class}.{func.name}" if func.enclosing_class else func.name
            func_id = f"func::{fr.path}::{qual_name}"
            node = {
                "id": func_id,
                "type": "function",
                "name": func.name,
                "qualified_name": qual_name,
                "kind": func.kind,
                "async": func.async_,
                "params": func.params,
                "decorators": func.decorators,
                "file": fr.path,
                "line": func.line,
                "enclosing_class": func.enclosing_class,
            }
            if func.source_text:
                node["source_text"] = func.source_text
            nodes.append(node)
            edges.append({
                "from": file_id,
                "to": func_id,
                "type": "contains",
            })

        # Call nodes
        for call in fr.calls:
            call_id = f"call::{fr.path}::L{call.line}::{call.callee}"
            node = {
                "id": call_id,
                "type": "call",
                "callee": call.callee,
                "file": fr.path,
                "line": call.line,
                "args_preview": call.args_preview,
            }
            if call.labels:
                node["labels"] = call.labels
            if call.captured_arg:
                node["captured_arg"] = call.captured_arg
            nodes.append(node)

        # Class nodes
        for cls in fr.classes:
            cls_id = f"class::{fr.path}::{cls.name}"
            node = {
                "id": cls_id,
                "type": "class",
                "name": cls.name,
                "bases": cls.bases,
                "decorators": cls.decorators,
                "methods": [{"name": m.name, "async": m.async_, "line": m.line} for m in cls.methods],
                "file": fr.path,
                "line": cls.line,
            }
            if cls.source_text:
                node["source_text"] = cls.source_text
            nodes.append(node)
            edges.append({
                "from": file_id,
                "to": cls_id,
                "type": "contains",
            })
            # Inheritance edges
            for base in cls.bases:
                edges.append({
                    "from": cls_id,
                    "to": None,  # resolved later or by consumer
                    "type": "inherits",
                    "target_name": base,
                })

    # Metadata
    labeled_calls = sum(
        1 for n in nodes if n["type"] == "call" and n.get("labels")
    )

    return {
        "metadata": {
            "extracted_at": datetime.now().isoformat(),
            "project": config.project.name,
            "project_root": str(config.project.root),
            "total_files": sum(1 for n in nodes if n["type"] == "file"),
            "total_functions": sum(1 for n in nodes if n["type"] == "function"),
            "total_classes": sum(1 for n in nodes if n["type"] == "class"),
            "total_calls": sum(1 for n in nodes if n["type"] == "call"),
            "total_labeled_calls": labeled_calls,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
        "nodes": nodes,
        "edges": edges,
    }
