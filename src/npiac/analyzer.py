from __future__ import annotations

from pathlib import Path

from .detectors import DETECTORS
from .models import DetectionResult, RepositoryContext
from .scanner import scan_repository
from .selectors import (
    render_tree,
    select_config_files,
    select_entry_points,
    select_important_files,
    select_test_paths,
    select_tree_paths,
)


def analyze_repository(path: str | Path, excluded_paths: set[str] | None = None) -> RepositoryContext:
    snapshot = scan_repository(path, excluded_paths)
    detection = DetectionResult()
    for detector in DETECTORS:
        try:
            detection.merge(detector.detect(snapshot))
        except Exception as exc:  # A detector must not prevent generic output.
            detection.warnings.append(f"{type(detector).__name__} failed: {type(exc).__name__}.")

    entry_points = select_entry_points(snapshot, detection)
    config_files = select_config_files(snapshot)
    candidates = sorted(detection.project_names, key=lambda item: (-item[0], item[1].casefold(), item[1]))
    project_name = candidates[0][1] if candidates else snapshot.root.name
    warnings = set(snapshot.warnings) | set(detection.warnings)
    tree_paths = select_tree_paths(snapshot)
    return RepositoryContext(
        project_name=project_name,
        is_git=snapshot.is_git,
        languages=tuple(sorted(detection.languages, key=str.casefold)),
        frameworks=tuple(sorted(detection.frameworks, key=str.casefold)),
        package_managers=tuple(sorted(detection.package_managers, key=str.casefold)),
        infrastructure=tuple(sorted(detection.infrastructure, key=str.casefold)),
        databases=tuple(sorted(detection.databases, key=str.casefold)),
        test_frameworks=tuple(sorted(detection.test_frameworks, key=str.casefold)),
        entry_points=tuple(sorted(entry_points.items(), key=lambda item: (item[0].casefold(), item[1].casefold()))),
        test_paths=select_test_paths(snapshot),
        config_files=config_files,
        important_files=select_important_files(snapshot, entry_points, config_files),
        tree=render_tree(tree_paths),
        notes=tuple(sorted(detection.notes, key=str.casefold)),
        warnings=tuple(sorted(warnings, key=str.casefold)),
        tree_paths=tree_paths,
    )
