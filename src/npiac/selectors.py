from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from .constants import (
    IMAGE_ASSET_SUFFIXES,
    MANIFEST_NAMES,
    MAX_CONFIG_FILES,
    MAX_IMPORTANT_FILES,
    MAX_TREE_DEPTH,
    MAX_TREE_ENTRIES,
    MAX_TREE_IMAGES_PER_DIRECTORY,
)
from .models import DetectionResult, ImportantFile, RepositorySnapshot
from .path_rules import (
    is_entry_eligible,
    is_sample_only_path,
    is_snapshot_artifact,
    is_workspace_path,
)


IMPORTANT_NAMES = {
    "pyproject.toml": "Python project manifest",
    "requirements.txt": "Python dependencies",
    "package.json": "JavaScript project manifest",
    "cargo.toml": "Rust project manifest",
    "readme.md": "Project documentation",
    "readme.rst": "Project documentation",
    "readme.txt": "Project documentation",
    "license": "Project license",
    "license.md": "Project license",
    "dockerfile": "Container build configuration",
    "docker-compose.yml": "Container orchestration configuration",
    "compose.yml": "Container orchestration configuration",
    ".gitignore": "Git ignore configuration",
    ".npiacignore": "NPIAC ignore configuration",
    ".repocontextignore": "NPIAC ignore configuration (legacy filename)",
}

CONFIG_NAMES = {
    "pyproject.toml",
    "package.json",
    "cargo.toml",
    "tsconfig.json",
    ".gitignore",
    ".repocontextignore",
    ".npiacignore",
    "global.json",
    "directory.build.props",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "pytest.ini",
    "setup.cfg",
    "tox.ini",
}

ENTRY_CANDIDATES = (
    ("manage.py", "Application"),
    ("main.py", "Application"),
    ("app.py", "Application"),
    ("src/main.py", "Application"),
    ("src/index.ts", "Application"),
    ("src/index.tsx", "Application"),
    ("src/index.js", "Application"),
    ("src/main.ts", "Application"),
    ("src/main.tsx", "Application"),
    ("src/main.js", "Application"),
    ("src/main.rs", "Binary"),
    ("src/lib.rs", "Library"),
    ("Program.cs", ".NET application"),
)

SOURCE_SUFFIXES = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".cs"})
TEST_DIRS = frozenset({"test", "tests", "__tests__"})
GENERATED_DIRS = frozenset({"generated", "gen", "out", "artifacts", "coverage"})
GENERIC_ENTRY_LABELS = frozenset({"Application", "Binary", "Library"})


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.split("/"))


def _is_test_file(path: str) -> bool:
    parts = _path_parts(path)
    name = parts[-1]
    stem = Path(name).stem
    return (
        any(part in TEST_DIRS or part.endswith(".tests") for part in parts[:-1])
        or stem.startswith("test_")
        or stem.endswith(("_test", ".test", ".spec", "tests"))
    )


def _canonical_stem(path: str) -> str:
    stem = Path(path).stem.casefold()
    stem = re.sub(r"^(test[_\-.]|tests[_\-.])", "", stem)
    stem = re.sub(r"([_\-.](test|tests|spec)|tests?)$", "", stem)
    return re.sub(r"[^a-z0-9]", "", stem)


def _has_term(path: str, terms: set[str]) -> bool:
    parts = _path_parts(path)
    stem_tokens = set(filter(None, re.split(r"[^a-z0-9]+", Path(path).stem.casefold())))
    return bool(set(parts[:-1]) & terms or stem_tokens & terms)


def _framework_convention(path: str) -> str | None:
    lowered = path.casefold()
    parts = _path_parts(path)
    name = parts[-1]
    if name in {"manage.py", "settings.py", "urls.py", "views.py", "asgi.py", "wsgi.py"}:
        return "Python framework conventional path"
    if any(part in {"pages", "app", "api"} for part in parts[:-1]) and Path(path).suffix.casefold() in {
        ".js", ".jsx", ".ts", ".tsx"
    }:
        return "JavaScript framework conventional path"
    if lowered in {"src/main.rs", "src/lib.rs"} or lowered.startswith("src/bin/"):
        return "Rust conventional source path"
    if name in {"program.cs", "startup.cs"} or any(
        part in {"controllers", "services", "models", "data"} for part in parts[:-1]
    ) and name.endswith(".cs"):
        return ".NET conventional project path"
    return None


def _manifest_distance(path: str, manifest_dirs: tuple[str, ...]) -> int | None:
    directory_parts = path.split("/")[:-1]
    distances: list[int] = []
    for directory in manifest_dirs:
        manifest_parts = directory.split("/") if directory else []
        if directory_parts[: len(manifest_parts)] == manifest_parts:
            distances.append(len(directory_parts) - len(manifest_parts))
    return min(distances) if distances else None


def _add_signal(signals: list[tuple[int, str]], score: int, reason: str) -> None:
    if score == 0:
        return
    if reason not in {existing_reason for _, existing_reason in signals}:
        signals.append((score, reason))


def _add_entry(entries: dict[str, str], label: str, path: str, *, specific: bool = False) -> None:
    if specific:
        for existing_label, existing_path in tuple(entries.items()):
            if existing_path == path and existing_label in GENERIC_ENTRY_LABELS:
                del entries[existing_label]
    key = label
    suffix = 2
    while key in entries and entries[key] != path:
        key = f"{label} {suffix}"
        suffix += 1
    entries.setdefault(key, path)


def _component_name(path: str) -> str:
    parts = path.split("/")
    if len(parts) == 3 and parts[1].casefold() == "src":
        return "" if parts[0].casefold() == "src" else parts[0]
    if len(parts) == 4 and is_workspace_path(path) and parts[2].casefold() == "src":
        return parts[1]
    return ""


def _component_entry(path: str, detection: DetectionResult) -> tuple[str, bool] | None:
    lowered = path.casefold()
    name = Path(path).name.casefold()
    component = _component_name(path)

    if lowered in {"src/main.tsx", "src/main.jsx"} and {
        "React", "Next.js", "Vite"
    } & detection.frameworks:
        return "Frontend", True
    if lowered in {"src-tauri/src/main.rs", "src-tauri/src/lib.rs"}:
        return "Tauri desktop", True
    if component and name == "main.rs":
        return f"Rust {component}", True
    if component and name in {"main.ts", "main.tsx", "main.js", "main.jsx", "index.ts", "index.tsx", "index.js", "index.jsx"}:
        if component.casefold() in {"client", "frontend", "ui", "web"}:
            return f"Frontend {component}", True
        return f"{component} application", True
    if component and name in {"main.py", "app.py"}:
        return f"Python application {component}", True
    return None


def _production_signals(
    path: str,
    entry_paths: set[str],
    config_paths: set[str],
    manifest_dirs: tuple[str, ...],
) -> list[tuple[int, str]]:
    signals: list[tuple[int, str]] = []
    name = Path(path).name.casefold()
    suffix = Path(path).suffix.casefold()
    parts = _path_parts(path)
    depth = path.count("/")
    sample_only = is_sample_only_path(path)

    if name in IMPORTANT_NAMES:
        if name in MANIFEST_NAMES:
            importance = 1_000
        elif name.startswith(("readme", "contributing", "license")):
            importance = 500
        elif name in {"dockerfile", "docker-compose.yml", "compose.yml"}:
            importance = 650
        else:
            importance = 550
        _add_signal(signals, importance, IMPORTANT_NAMES[name])
    elif name.endswith((".csproj", ".sln")):
        _add_signal(signals, 1_000, ".NET project definition")
    elif name.startswith(("readme", "contributing", "license")):
        _add_signal(signals, 500, "Project documentation")
    if not sample_only and (path in entry_paths or (
        suffix in SOURCE_SUFFIXES
        and name in {"main.py", "app.py", "index.js", "index.ts", "index.tsx", "main.rs", "lib.rs", "program.cs", "startup.cs"}
        and (depth <= 2 or parts[0] == "src" or is_workspace_path(path))
    )):
        _add_signal(signals, 900, "Probable entry point")
    if path in config_paths:
        _add_signal(signals, 700, "Project configuration")

    if suffix in SOURCE_SUFFIXES:
        if _has_term(path, {"route", "routes", "router", "routers", "controller", "controllers", "endpoint", "endpoints", "views", "urls"}):
            _add_signal(signals, 560, "Route or controller implementation")
        if _has_term(path, {"service", "services", "usecase", "usecases", "handler", "handlers", "command", "commands"}):
            _add_signal(signals, 540, "Service or business-logic implementation")
        if _has_term(path, {"model", "models", "entity", "entities", "schema", "schemas", "domain"}):
            _add_signal(signals, 520, "Model, entity, or schema definition")
        if _has_term(path, {"repository", "repositories", "database", "db", "data", "persistence", "storage", "migration", "migrations"}):
            _add_signal(signals, 500, "Database or repository implementation")
        convention = _framework_convention(path)
        if convention:
            _add_signal(signals, 360, convention)

    distance = _manifest_distance(path, manifest_dirs)
    if distance is not None:
        proximity_score = max(0, 70 - distance * 12)
        if proximity_score:
            _add_signal(signals, proximity_score, "Near a project manifest or configuration root")

    if depth >= 4 and _has_term(path, {"util", "utils", "utility", "utilities", "helper", "helpers", "common", "shared"}):
        _add_signal(signals, -220 - depth * 8, "Deeply nested low-signal utility penalty")
    else:
        _add_signal(signals, -depth * 4, "Path depth penalty")

    if any(part in GENERATED_DIRS for part in parts[:-1]) or name.endswith((".g.cs", ".designer.cs")) or ".generated." in name:
        _add_signal(signals, -900, "Generated-file penalty")
    if any(part in {"snapshot", "snapshots", "__snapshots__"} for part in parts[:-1]) or name.endswith((".snap", ".snapshot")):
        _add_signal(signals, -900, "Snapshot penalty")
    if any(part in {"vendor", "build", "dist", "target", "bin", "obj"} for part in parts[:-1]):
        _add_signal(signals, -800, "Vendor or build-output penalty")
    if sample_only:
        _add_signal(signals, -1_200, "Sample-only path penalty")
    return signals


def select_entry_points(snapshot: RepositorySnapshot, detection: DetectionResult) -> dict[str, str]:
    paths = {path for path in snapshot.paths if is_entry_eligible(path)}
    entries = {label: path for label, path in detection.entry_points.items() if path in paths}
    for candidate, label in ENTRY_CANDIDATES:
        if candidate in paths:
            _add_entry(entries, label, candidate)
    for path in sorted(paths, key=str.casefold):
        workspace_name = path.split("/")[1] if is_workspace_path(path) else ""
        component_entry = _component_entry(path, detection)
        if component_entry:
            label, specific = component_entry
            _add_entry(entries, label, path, specific=specific)
        if path.startswith("src/") and path.endswith(("/main.py", "/app.py")):
            entries.setdefault(f"Python application {Path(path).parent.name}", path)
        if is_workspace_path(path) and path.endswith(("/main.py", "/app.py", "/index.js", "/index.ts", "/index.tsx")):
            entries.setdefault(f"Workspace application {workspace_name}", path)
        if (path.startswith("src/bin/") or is_workspace_path(path)) and path.endswith(".rs") and (
            path.endswith("/main.rs") or "/src/bin/" in path
        ):
            entries.setdefault(f"Rust binary {workspace_name or Path(path).stem}", path)
        if path.casefold().endswith("/program.cs"):
            entries.setdefault(f".NET application {Path(path).parent.name}", path)
    return entries


def select_tree_paths(snapshot: RepositorySnapshot) -> tuple[str, ...]:
    image_counts: dict[str, int] = {}
    for path in snapshot.paths:
        if Path(path).suffix.casefold() in IMAGE_ASSET_SUFFIXES:
            parent = Path(path).parent.as_posix()
            image_counts[parent] = image_counts.get(parent, 0) + 1
    return tuple(
        path
        for path in snapshot.paths
        if Path(path).suffix.casefold() not in IMAGE_ASSET_SUFFIXES
        or image_counts.get(Path(path).parent.as_posix(), 0) <= MAX_TREE_IMAGES_PER_DIRECTORY
    )


def select_test_paths(snapshot: RepositorySnapshot) -> tuple[str, ...]:
    found: set[str] = set()
    for path in snapshot.paths:
        parts = path.split("/")
        for index, part in enumerate(parts[:-1]):
            lowered = part.casefold()
            if lowered in {"test", "tests", "__tests__"} or lowered.endswith(".tests"):
                found.add("/".join(parts[: index + 1]) + "/")
                break
        name = parts[-1].casefold()
        if name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js")):
            found.add(path)
    return tuple(sorted(found, key=str.casefold))


def select_config_files(snapshot: RepositorySnapshot) -> tuple[str, ...]:
    configs = []
    for path in snapshot.paths:
        if is_sample_only_path(path) or is_snapshot_artifact(path):
            continue
        name = Path(path).name.casefold()
        if (
            name in CONFIG_NAMES
            or name.endswith((".csproj", ".sln"))
            or path.casefold().startswith(".github/workflows/")
            or name.startswith("appsettings") and name.endswith(".json")
        ):
            configs.append(path)
    return tuple(sorted(configs, key=str.casefold)[:MAX_CONFIG_FILES])


def select_important_files(
    snapshot: RepositorySnapshot,
    entry_points: dict[str, str],
    config_files: Iterable[str],
) -> tuple[ImportantFile, ...]:
    entry_paths = set(entry_points.values())
    config_paths = set(config_files)
    manifest_names = set(IMPORTANT_NAMES) | CONFIG_NAMES
    manifest_directory_set: set[str] = set()
    for path in snapshot.paths:
        if is_snapshot_artifact(path):
            continue
        name = Path(path).name.casefold()
        if not is_sample_only_path(path) and (name in manifest_names or name.endswith((".csproj", ".sln"))):
            directory = Path(path).parent.as_posix()
            manifest_directory_set.add("" if directory == "." else directory.strip("/"))
    manifest_dirs = tuple(sorted(manifest_directory_set, key=str.casefold))

    production_paths = {
        path
        for path in snapshot.paths
        if Path(path).suffix.casefold() in SOURCE_SUFFIXES
        and not _is_test_file(path)
        and not is_sample_only_path(path)
    }
    production_keys = {
        (_canonical_stem(path), Path(path).suffix.casefold())
        for path in production_paths
        if _canonical_stem(path)
    }
    semantic_stems: set[str] = set()
    signals_by_path: dict[str, list[tuple[int, str]]] = {}

    semantic_reasons = {
        "Probable entry point",
        "Route or controller implementation",
        "Service or business-logic implementation",
        "Model, entity, or schema definition",
        "Database or repository implementation",
    }
    test_allowed_reasons = {
        "Near a project manifest or configuration root",
        "Path depth penalty",
        "Deeply nested low-signal utility penalty",
        "Generated-file penalty",
        "Snapshot penalty",
        "Vendor or build-output penalty",
    }

    for path in snapshot.paths:
        if is_snapshot_artifact(path):
            continue
        signals = _production_signals(path, entry_paths, config_paths, manifest_dirs)
        if _is_test_file(path):
            signals = [(score, reason) for score, reason in signals if reason in test_allowed_reasons]
        elif any(reason in semantic_reasons for _, reason in signals):
            canonical = _canonical_stem(path)
            if canonical:
                semantic_stems.add(canonical)
        signals_by_path[path] = signals

    for path, signals in signals_by_path.items():
        canonical = _canonical_stem(path)
        suffix = Path(path).suffix.casefold()
        if _is_test_file(path) and canonical and any(
            canonical == production_stem
            or len(canonical) >= 4 and (canonical in production_stem or production_stem in canonical)
            for production_stem in semantic_stems
        ):
            _add_signal(signals, 380, "Test related to an important source file")
            _add_signal(signals, -120, "Test-file priority adjustment")
        if is_sample_only_path(path) and (canonical, suffix) in production_keys:
            _add_signal(signals, -1_400, "Duplicated example or fixture penalty")

    ranked: list[ImportantFile] = []
    for path, signals in signals_by_path.items():
        score = sum(value for value, _ in signals)
        if score < 120 or not any(value > 0 for value, _ in signals):
            continue
        ordered_signals = sorted(signals, key=lambda item: (-item[0], item[1].casefold(), item[1]))
        reasons = tuple(reason for _, reason in ordered_signals)
        generic_reasons = {
            "Project configuration",
            "Near a project manifest or configuration root",
            "Python framework conventional path",
            "JavaScript framework conventional path",
            "Rust conventional source path",
            ".NET conventional project path",
        }
        specific_signals = [
            (value, reason)
            for value, reason in ordered_signals
            if value > 0 and reason not in generic_reasons
        ]
        primary_reason = (specific_signals or ordered_signals)[0][1]
        ranked.append(ImportantFile(path, primary_reason, score, reasons))

    ranked.sort(key=lambda item: (-item.score, item.path.casefold(), item.path))
    return tuple(ranked[:MAX_IMPORTANT_FILES])


def render_tree(paths: Iterable[str]) -> str:
    tree: dict[str, dict] = {}
    for path in sorted(paths, key=lambda value: (value.casefold(), value)):
        parts = path.split("/")
        node = tree
        for part in parts:
            node = node.setdefault(part, {})

    lines = ["."]
    emitted = 0
    truncated = False

    def visit(node: dict[str, dict], prefix: str, depth: int) -> None:
        nonlocal emitted, truncated
        names = sorted(node, key=lambda value: (value.casefold(), value))
        for index, name in enumerate(names):
            if emitted >= MAX_TREE_ENTRIES:
                truncated = True
                return
            last = index == len(names) - 1
            children = node[name]
            display = name + ("/" if children else "")
            lines.append(prefix + ("└── " if last else "├── ") + display)
            emitted += 1
            if children:
                child_prefix = prefix + ("    " if last else "│   ")
                if depth >= MAX_TREE_DEPTH:
                    lines.append(child_prefix + "└── …")
                else:
                    visit(children, child_prefix, depth + 1)
            if truncated:
                return

    visit(tree, "", 1)
    if truncated:
        lines.append("└── … (tree truncated)")
    return "\n".join(lines)
