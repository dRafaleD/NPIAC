from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    pattern: str
    negated: bool = False
    directory_only: bool = False

    def matches(self, path: str) -> bool:
        parts = path.split("/")
        pattern = self.pattern.removeprefix("/")
        if "/" in pattern:
            if self.directory_only:
                return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, f"{pattern}/*")
            return fnmatch.fnmatchcase(path, pattern)
        candidates = parts[:-1] if self.directory_only else parts
        return any(fnmatch.fnmatchcase(part, pattern) for part in candidates)


def _load_ignore_file(ignore_file: Path) -> list[IgnoreRule]:
    if not ignore_file.is_file() or ignore_file.is_symlink():
        return []
    try:
        lines = ignore_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
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


def is_ignored(path: str, rules: tuple[IgnoreRule, ...]) -> bool:
    ignored = False
    for rule in rules:
        if rule.matches(path):
            ignored = not rule.negated
    return ignored
