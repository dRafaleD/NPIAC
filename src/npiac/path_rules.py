from __future__ import annotations

import fnmatch
from pathlib import Path


SAMPLE_ONLY_DIRS = frozenset(
    {
        "demo",
        "demos",
        "example",
        "examples",
        "fixture",
        "fixtures",
        "playground",
        "sample",
        "samples",
        "sandbox",
        "test-data",
        "testdata",
        "tutorial",
        "tutorials",
    }
)
SNAPSHOT_DIRS = frozenset({"__snapshots__", "golden", "goldens", "snapshot", "snapshots"})
TEST_DIRS = frozenset({"__tests__", "test", "tests"})
WORKSPACE_DIRS = frozenset({"apps", "crates", "modules", "packages", "projects", "services"})


def path_parts(path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.replace("\\", "/").split("/") if part)


def is_sample_only_path(path: str) -> bool:
    directories = path_parts(path)[:-1]
    for index, part in enumerate(directories):
        if part in SNAPSHOT_DIRS:
            return True
        if part in SAMPLE_ONLY_DIRS:
            # `src/sample` is a common real package name and may be referenced by project metadata.
            if part == "sample" and index > 0 and directories[index - 1] == "src":
                continue
            return True
    return False


def is_test_path(path: str) -> bool:
    return any(part in TEST_DIRS or part.endswith(".tests") for part in path_parts(path)[:-1])


def is_snapshot_artifact(path: str) -> bool:
    parts = path_parts(path)
    name = parts[-1] if parts else ""
    return bool(set(parts[:-1]) & SNAPSHOT_DIRS) or name.endswith((".snap", ".snapshot"))


def is_entry_eligible(path: str) -> bool:
    return not is_sample_only_path(path) and not is_test_path(path) and not is_snapshot_artifact(path)


def is_workspace_path(path: str) -> bool:
    parts = path_parts(path)
    return bool(parts and parts[0] in WORKSPACE_DIRS and len(parts) >= 3)


def is_generated_context_file(path: str) -> bool:
    return fnmatch.fnmatchcase(Path(path).name.casefold(), "context*.md")
