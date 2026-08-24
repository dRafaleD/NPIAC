from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .constants import BINARY_RELEASE_SUFFIXES, GENERATED_MARKER, SENSITIVE_NAMES, SENSITIVE_SUFFIXES, SKIPPED_DIRS
from .ignore import is_ignored, load_ignore_rules
from .models import FileInfo, RepositorySnapshot
from .path_rules import is_generated_context_file


def _sort_key(path: str) -> tuple[str, str]:
    return (path.casefold(), path)


def _is_sensitive(path: str) -> bool:
    name = Path(path).name.casefold()
    return (
        name in SENSITIVE_NAMES
        or name.startswith(".env.")
        or name.endswith(SENSITIVE_SUFFIXES)
        or name.startswith("credentials.")
    )


def _is_binary_release(path: str) -> bool:
    return Path(path).suffix.casefold() in BINARY_RELEASE_SUFFIXES


def _is_npiac_generated_markdown(path: Path) -> bool:
    if path.suffix.casefold() != ".md":
        return False
    marker = GENERATED_MARKER.encode("utf-8")
    previous = b""
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(8_192):
                searchable = previous + chunk
                if marker in searchable:
                    return True
                previous = searchable[-len(marker) + 1 :]
    except OSError:
        return False
    return False


def _skip_directory(name: str, parent: Path) -> bool:
    lowered = name.casefold()
    parent_name = parent.name.casefold()
    if lowered in {"release", "releases"}:
        return parent_name not in {"docs", "documentation"}
    if lowered in {"generated", "gen"} and parent_name in {"schema", "schemas"}:
        return True
    if lowered in {"schema", "schemas"} and parent_name in {"generated", "gen"}:
        return True
    return lowered in SKIPPED_DIRS or lowered.endswith(".egg-info")


def _is_skipped(path: str) -> bool:
    parts = Path(path).parts
    for index, part in enumerate(parts[:-1]):
        parent = Path(parts[index - 1]) if index else Path("")
        if _skip_directory(part, parent):
            return True
    return False


def _git_files(root: Path) -> tuple[list[str] | None, bool, str | None]:
    if not (root / ".git").exists():
        return None, False, None
    if not shutil.which("git"):
        return None, False, "Git is unavailable; used filesystem scanning."
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if Path(top).resolve() != root:
            return None, True, "Analyzed path is below the Git root; used filesystem scanning."
        output = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        return output.splitlines(), True, None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, False, "Git scanning failed; used filesystem scanning."


def _filesystem_files(root: Path) -> list[str]:
    paths: list[str] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if not _skip_directory(name, current_path)
            and not (current_path / name).is_symlink()
        ]
        for name in files:
            full_path = current_path / name
            if full_path.is_symlink():
                continue
            paths.append(full_path.relative_to(root).as_posix())
    return paths


def scan_repository(path: str | Path, excluded_paths: set[str] | None = None) -> RepositorySnapshot:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {root}")

    excluded = {item.replace("\\", "/") for item in (excluded_paths or set())}
    ignore_rules = load_ignore_rules(root)
    git_paths, is_git, warning = _git_files(root)
    raw_paths = git_paths if git_paths is not None else _filesystem_files(root)
    warnings = [warning] if warning else []
    files: list[FileInfo] = []
    for relative in sorted(set(raw_paths), key=_sort_key):
        normalized = relative.replace("\\", "/").removeprefix("./")
        if (
            normalized in excluded
            or is_generated_context_file(normalized)
            or Path(normalized).name == ".gitkeep"
            or _is_skipped(normalized)
            or _is_binary_release(normalized)
            or _is_sensitive(normalized)
            or is_ignored(normalized, ignore_rules)
        ):
            continue
        full_path = root / Path(normalized)
        try:
            if full_path.is_symlink() or not full_path.is_file():
                continue
            if _is_npiac_generated_markdown(full_path):
                continue
            files.append(FileInfo(normalized, full_path.stat().st_size))
        except OSError:
            warnings.append(f"Could not inspect `{normalized}`.")
    return RepositorySnapshot(root, tuple(files), is_git, tuple(sorted(set(warnings))))
