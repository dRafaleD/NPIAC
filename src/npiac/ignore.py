from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from .constants import MAX_IGNORE_FILE_BYTES
from .safety import is_link


class IgnoreFileError(OSError):
    """An ignore file could not be applied safely."""


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    pattern: str
    negated: bool = False
    directory_only: bool = False

    def matches(self, path: str) -> bool:
        parts = path.split("/")
        pattern = self.pattern.removeprefix("/")
        if "/" in pattern:
            return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, f"{pattern}/*")
        candidates = parts[:-1] if self.directory_only else parts
        return any(fnmatch.fnmatchcase(part, pattern) for part in candidates)


def _load_ignore_file(ignore_file: Path) -> list[IgnoreRule]:
    if not ignore_file.exists() and not is_link(ignore_file):
        return []
    if is_link(ignore_file) or not ignore_file.is_file():
        raise IgnoreFileError(f"Refusing unsafe ignore file: {ignore_file.name}")
    try:
        with ignore_file.open("rb") as handle:
            raw = handle.read(MAX_IGNORE_FILE_BYTES + 1)
        if len(raw) > MAX_IGNORE_FILE_BYTES:
            raise IgnoreFileError(f"Ignore file exceeds {MAX_IGNORE_FILE_BYTES} bytes: {ignore_file.name}")
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise IgnoreFileError(f"Ignore file is not valid UTF-8: {ignore_file.name}") from exc
    except OSError as exc:
        if isinstance(exc, IgnoreFileError):
            raise
        raise IgnoreFileError(f"Could not safely read ignore file: {ignore_file.name}") from exc
    rules: list[IgnoreRule] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        directory_only = line.endswith("/")
        line = line.rstrip("/").replace("\\", "/")
        if line:
            rules.append(IgnoreRule(line, negated, directory_only))
    return rules


def load_ignore_rules(root: Path) -> tuple[IgnoreRule, ...]:
    rules: list[IgnoreRule] = []
    # Apply the legacy file first so the NPIAC-branded file can override it.
    for name in (".repocontextignore", ".npiacignore"):
        rules.extend(_load_ignore_file(root / name))
    return tuple(rules)


def load_gitignore_rules(root: Path) -> tuple[IgnoreRule, ...]:
    return tuple(_load_ignore_file(root / ".gitignore"))


def is_ignored(path: str, rules: tuple[IgnoreRule, ...]) -> bool:
    ignored = False
    for rule in rules:
        if rule.matches(path):
            ignored = not rule.negated
    return ignored
