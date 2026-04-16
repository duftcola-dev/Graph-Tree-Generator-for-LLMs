"""Import path resolution — resolves Python import specifiers to project-relative file paths."""

from __future__ import annotations

from pathlib import Path

from .config import ResolveConfig


class ImportResolver:
    """Resolves Python import specifiers to project-relative paths."""

    def __init__(self, project_root: Path, config: ResolveConfig):
        self.root = project_root
        self.config = config

    def resolve(self, specifier: str, from_file: Path) -> str | None:
        """Resolve an import specifier to a project-relative path, or None for external.

        Args:
            specifier: The import string (e.g. "os.path", ".utils", "..models.user")
            from_file: Absolute path of the importing file

        Returns:
            Project-relative posix path string, or None if external/unresolved
        """
        # Relative imports (start with dots)
        if specifier.startswith("."):
            return self._resolve_relative(specifier, from_file)

        # Absolute imports — try to find within the project
        return self._resolve_absolute(specifier)

    def _resolve_relative(self, specifier: str, from_file: Path) -> str | None:
        """Resolve a relative import (e.g. .utils, ..models.user)."""
        # Count leading dots
        dots = 0
        for c in specifier:
            if c == ".":
                dots += 1
            else:
                break

        remainder = specifier[dots:]

        # Start from the importing file's package directory
        base = from_file.parent
        # Go up (dots - 1) levels (one dot = current package)
        for _ in range(dots - 1):
            base = base.parent

        if remainder:
            parts = remainder.split(".")
            candidate = base / "/".join(parts)
        else:
            candidate = base

        return self._try_python_path(candidate)

    def _resolve_absolute(self, specifier: str) -> str | None:
        """Resolve an absolute import within the project."""
        parts = specifier.split(".")

        # Try from project root
        result = self._try_from_base(self.root, parts)
        if result:
            return result

        # Try from configured src roots
        for src_root in self.config.src_roots:
            src_path = self.root / src_root
            result = self._try_from_base(src_path, parts)
            if result:
                return result

        if self.config.skip_external:
            return None

        return None

    def _try_from_base(self, base: Path, parts: list[str]) -> str | None:
        """Try to resolve module parts from a base directory."""
        candidate = base / "/".join(parts)
        return self._try_python_path(candidate)

    def _try_python_path(self, candidate: Path) -> str | None:
        """Try candidate as a Python module path (.py file or package __init__.py)."""
        # Direct .py file
        py_file = candidate.with_suffix(".py")
        if py_file.is_file():
            return self._to_relative(py_file)

        # Package directory with __init__.py
        init_file = candidate / "__init__.py"
        if init_file.is_file():
            return self._to_relative(init_file)

        return None

    def _to_relative(self, absolute: Path) -> str | None:
        """Convert absolute path to project-relative posix string."""
        try:
            return absolute.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return None
