from __future__ import annotations

from typing import Protocol

from ..models import DetectionResult, RepositorySnapshot
from ..path_rules import is_sample_only_path, is_snapshot_artifact


def analysis_paths(snapshot: RepositorySnapshot) -> set[str]:
    """Return files that can describe the project rather than test sample projects."""
    return {
        path
        for path in snapshot.paths
        if not is_sample_only_path(path) and not is_snapshot_artifact(path)
    }


class Detector(Protocol):
    def detect(self, snapshot: RepositorySnapshot) -> DetectionResult: ...
