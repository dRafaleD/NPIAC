from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

from .constants import (
    BINARY_RELEASE_SUFFIXES,
    GENERATED_MARKER,
    MAX_GIT_OUTPUT_BYTES,
    MAX_SCANNED_DIRECTORIES,
    MAX_SCANNED_FILES,
    SKIPPED_DIRS,
)
from .ignore import is_ignored, load_gitignore_rules, load_ignore_rules
from .models import FileInfo, RepositorySnapshot
from .path_rules import is_generated_context_file
from .safety import is_link, is_sensitive_path, normalize_repository_path, resolve_repository_file


def _sort_key(path: str) -> tuple[str, str]:
    return (path.casefold(), path)


def _is_sensitive(path: str) -> bool:
    return is_sensitive_path(path)


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
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if Path(top).resolve() != root:
            return None, True, "Analyzed path is below the Git root; used filesystem scanning."
        command = ["git", "-c", "core.fsmonitor=false", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if process.stdout is None:
            process.kill()
            raise OSError("Git stdout pipe was unavailable")
        chunks: list[bytes] = []
        total = 0
        reader_error: list[BaseException] = []

        def read_stdout() -> None:
            nonlocal total
            try:
                while chunk := process.stdout.read(65_536):
                    total += len(chunk)
                    if total > MAX_GIT_OUTPUT_BYTES:
                        reader_error.append(ValueError("Git file listing exceeded the safety limit"))
                        process.kill()
                        return
                    chunks.append(chunk)
            except (OSError, ValueError) as exc:
                reader_error.append(exc)
                process.kill()

        reader = threading.Thread(target=read_stdout, name="npiac-git-reader", daemon=True)
        reader.start()
        try:
            return_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            raise
        finally:
            reader.join(timeout=5)
            process.stdout.close()
        if reader.is_alive():
            process.kill()
            raise subprocess.TimeoutExpired(command, 35)
        if reader_error:
            raise reader_error[0]
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)
        output = b"".join(chunks)
        return [os.fsdecode(item) for item in output.split(b"\0") if item], True, None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, False, "Git scanning failed; used filesystem scanning."


def _filesystem_files(root: Path) -> tuple[list[str], bool]:
    paths: list[str] = []
    visited_directories = 0
    for current, dirs, files in os.walk(root, followlinks=False):
        visited_directories += 1
        if visited_directories > MAX_SCANNED_DIRECTORIES:
            return paths, True
        current_path = Path(current)
        dirs[:] = [
            name
            for name in sorted(dirs, key=lambda value: (value.casefold(), value))
            if not _skip_directory(name, current_path)
            and not is_link(current_path / name)
        ]
        for name in sorted(files, key=lambda value: (value.casefold(), value)):
            full_path = current_path / name
            if is_link(full_path):
                continue
            paths.append(full_path.relative_to(root).as_posix())
            if len(paths) > MAX_SCANNED_FILES:
                return paths, True
    return paths, False


def scan_repository(path: str | Path, excluded_paths: set[str] | None = None) -> RepositorySnapshot:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Repository path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Repository path is not a directory: {root}")

    excluded = {
        normalized
        for item in (excluded_paths or set())
        if (normalized := normalize_repository_path(item)) is not None
    }
    excluded_keys = {os.path.normcase(item) for item in excluded}
    ignore_rules = load_ignore_rules(root)
    git_paths, is_git, warning = _git_files(root)
    filesystem_limited = False
    if git_paths is not None:
        raw_paths = git_paths
    else:
        raw_paths, filesystem_limited = _filesystem_files(root)
    warnings = [warning] if warning else []
    if filesystem_limited:
        warnings.append("Filesystem scan stopped at the configured resource safety limit.")
    gitignore_rules = load_gitignore_rules(root) if git_paths is None else ()
    files: list[FileInfo] = []
    unsafe_paths = 0
    ordered_paths = sorted(set(raw_paths), key=_sort_key)
    if len(ordered_paths) > MAX_SCANNED_FILES:
        ordered_paths = ordered_paths[:MAX_SCANNED_FILES]
        warnings.append(f"Repository scan was limited to {MAX_SCANNED_FILES} files.")
    for relative in ordered_paths:
        normalized = normalize_repository_path(relative)
        if normalized is None:
            unsafe_paths += 1
            continue
        if (
            os.path.normcase(normalized) in excluded_keys
            or is_generated_context_file(normalized)
            or Path(normalized).name == ".gitkeep"
            or _is_skipped(normalized)
            or _is_binary_release(normalized)
            or _is_sensitive(normalized)
            or is_ignored(normalized, gitignore_rules)
            or is_ignored(normalized, ignore_rules)
        ):
            continue
        full_path = resolve_repository_file(root, normalized)
        if full_path is None:
            unsafe_paths += 1
            continue
        try:
            if _is_npiac_generated_markdown(full_path):
                continue
            files.append(FileInfo(normalized, full_path.stat().st_size))
        except OSError:
            warnings.append("Could not inspect one repository file safely.")
    if unsafe_paths:
        warnings.append(f"Skipped {unsafe_paths} unsafe repository path(s).")
    return RepositorySnapshot(root, tuple(files), is_git, tuple(sorted(set(warnings))))
