"""tree-sitter orchestration — parse Python files and run visitors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_python as tspy
from tree_sitter import Language, Parser

from .config import ExtractorConfig
from .visitors.imports import ImportInfo, extract_imports
from .visitors.functions import FunctionInfo, extract_functions
from .visitors.calls import CallInfo, extract_calls
from .visitors.classes import ClassInfo, extract_classes

# Pre-built language object
PY_LANG = Language(tspy.language())


@dataclass
class FileResult:
    """Extraction result for a single file."""
    path: str  # relative to project root
    imports: list[ImportInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)


def parse_file(source: bytes) -> object:
    """Parse source bytes with tree-sitter, return the Tree."""
    parser = Parser(PY_LANG)
    return parser.parse(source)


def extract_file(
    file_path: Path,
    project_root: Path,
    config: ExtractorConfig,
) -> FileResult | None:
    """Parse a single file and run all enabled visitors."""
    if file_path.suffix.lower() != ".py":
        return None

    source = file_path.read_bytes()
    tree = parse_file(source)
    root_node = tree.root_node
    rel_path = file_path.relative_to(project_root).as_posix()

    result = FileResult(path=rel_path)

    if config.extract.imports:
        result.imports = extract_imports(root_node, source)

    if config.extract.functions:
        result.functions = extract_functions(root_node, source)

    if config.extract.calls:
        result.calls = extract_calls(root_node, source)

    if config.extract.classes:
        result.classes = extract_classes(root_node, source)

    return result
