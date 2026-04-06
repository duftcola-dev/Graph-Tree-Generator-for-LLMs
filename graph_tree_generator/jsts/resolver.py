"""Import path resolution — resolves specifiers to project-relative file paths."""

from __future__ import annotations

import json
from pathlib import Path

from .config import ResolveConfig


class ImportResolver:
    """Resolves import specifiers to project-relative paths."""

    def __init__(self, project_root: Path, config: ResolveConfig):
        self.root = project_root
        self.config = config
        self._base_url: str | None = None
        self._paths: dict[str, list[str]] = {}
        self._load_tsconfig()

    def _load_tsconfig(self):
        """Read baseUrl and paths from tsconfig.json if configured."""
        if not self.config.tsconfig:
            return
        tsconfig_path = self.root / self.config.tsconfig
        if not tsconfig_path.exists():
            return
        try:
            with open(tsconfig_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            compiler = raw.get("compilerOptions", {})
            self._base_url = compiler.get("baseUrl")
            self._paths = compiler.get("paths", {})
        except (json.JSONDecodeError, OSError):
            pass

    def resolve(self, specifier: str, from_file: Path) -> str | None:
        """Resolve an import specifier to a project-relative path, or None for external.

        Args:
            specifier: The import string (e.g. "./foo", "../bar", "express", "api/utils")
            from_file: Absolute path of the importing file

        Returns:
            Project-relative posix path string, or None if external/unresolved
        """
        # 1. Relative imports
        if specifier.startswith("."):
            return self._resolve_relative(specifier, from_file)

        # 2. Manual aliases from config
        for alias_prefix, alias_target in self.config.alias.items():
            if specifier == alias_prefix or specifier.startswith(alias_prefix + "/"):
                remainder = specifier[len(alias_prefix):]
                resolved_spec = alias_target + remainder
                return self._resolve_from_root(resolved_spec)

        # 3. tsconfig paths aliases
        for pattern, targets in self._paths.items():
            prefix = pattern.removesuffix("*")
            if specifier.startswith(prefix):
                remainder = specifier[len(prefix):]
                for target in targets:
                    target_prefix = target.removesuffix("*")
                    resolved_spec = target_prefix + remainder
                    result = self._resolve_from_root(resolved_spec)
                    if result:
                        return result

        # 4. tsconfig baseUrl (non-relative imports resolved from baseUrl)
        if self._base_url:
            result = self._resolve_from_root(self._base_url + "/" + specifier)
            if result:
                return result

        # 5. External / node_modules — skip
        if self.config.skip_external:
            return None

        return None

    def _resolve_relative(self, specifier: str, from_file: Path) -> str | None:
        """Resolve a relative import (./foo, ../bar)."""
        base_dir = from_file.parent
        candidate = (base_dir / specifier).resolve()
        return self._try_extensions(candidate)

    def _resolve_from_root(self, rel_path: str) -> str | None:
        """Resolve a path relative to the project root."""
        candidate = (self.root / rel_path).resolve()
        return self._try_extensions(candidate)

    def _try_extensions(self, candidate: Path) -> str | None:
        """Try candidate with each configured extension suffix."""
        # Direct match (already has extension)
        if candidate.is_file():
            return self._to_relative(candidate)

        # Try appending extensions
        for ext in self.config.extensions:
            if ext.startswith("/"):
                # Directory index: /index.js, /index.ts
                test = candidate / ext.lstrip("/")
            else:
                test = candidate.parent / (candidate.name + ext)
            if test.is_file():
                return self._to_relative(test)

        return None

    def _to_relative(self, absolute: Path) -> str | None:
        """Convert absolute path to project-relative posix string."""
        try:
            return absolute.relative_to(self.root).as_posix()
        except ValueError:
            return None
