"""tree-sitter orchestration — parse JS/TS files and run visitors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from .config import ExtractorConfig
from .visitors.imports import ImportInfo, extract_imports
from .visitors.exports import ExportInfo, extract_exports
from .visitors.functions import FunctionInfo, extract_functions
from .visitors.calls import CallInfo, extract_calls
from .visitors.classes import ClassInfo, extract_classes
from .visitors.types import TypeInfo, extract_types

# Pre-built language objects
JS_LANG = Language(tsjs.language())
TS_LANG = Language(tsts.language_typescript())
TSX_LANG = Language(tsts.language_tsx())

# Extension to language mapping
_EXT_MAP = {
    ".js": JS_LANG,
    ".jsx": JS_LANG,
    ".mjs": JS_LANG,
    ".cjs": JS_LANG,
    ".ts": TS_LANG,
    ".tsx": TSX_LANG,
    ".mts": TS_LANG,
}


@dataclass
class FileResult:
    """Extraction result for a single file."""
    path: str  # relative to project root
    imports: list[ImportInfo] = field(default_factory=list)
    exports: list[ExportInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    types: list[TypeInfo] = field(default_factory=list)


def get_language(file_path: Path) -> Language | None:
    """Return the tree-sitter Language for a file, or None if unsupported."""
    return _EXT_MAP.get(file_path.suffix.lower())


def parse_file(source: bytes, language: Language) -> object:
    """Parse source bytes with tree-sitter, return the Tree."""
    parser = Parser(language)
    return parser.parse(source)


def extract_file(
    file_path: Path,
    project_root: Path,
    config: ExtractorConfig,
) -> FileResult | None:
    """Parse a single file and run all enabled visitors."""
    language = get_language(file_path)
    if language is None:
        return None

    source = file_path.read_bytes()
    tree = parse_file(source, language)
    root_node = tree.root_node
    rel_path = file_path.relative_to(project_root).as_posix()

    result = FileResult(path=rel_path)

    if config.extract.imports:
        result.imports = extract_imports(root_node, source)

    if config.extract.exports:
        result.exports = extract_exports(root_node, source)

    if config.extract.functions:
        result.functions = extract_functions(root_node, source)

    if config.extract.calls:
        result.calls = extract_calls(root_node, source)

    if config.extract.classes:
        result.classes = extract_classes(root_node, source)

    is_ts = file_path.suffix.lower() in (".ts", ".tsx", ".mts")
    if config.extract.types and is_ts:
        result.types = extract_types(root_node, source)

    return result
