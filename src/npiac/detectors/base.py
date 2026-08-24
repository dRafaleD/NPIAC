from __future__ import annotations

from typing import Protocol

from ..constants import MAX_MANIFEST_BYTES
from ..models import DetectionResult, RepositorySnapshot
from ..path_rules import is_sample_only_path, is_snapshot_artifact
from ..safety import resolve_repository_file


class ManifestTooLargeError(OSError):
    """A manifest exceeded the deterministic parser safety bound."""


def read_manifest_text(snapshot: RepositorySnapshot, path: str) -> str:
    full_path = resolve_repository_file(snapshot.root, path)
    if full_path is None:
        raise OSError("Manifest path is no longer a safe repository file")
    with full_path.open("rb") as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestTooLargeError(f"Manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    return raw.decode("utf-8")


def analysis_paths(snapshot: RepositorySnapshot) -> set[str]:
    """Return files that can describe the project rather than test sample projects."""
    return {
        path
        for path in snapshot.paths
        if not is_sample_only_path(path) and not is_snapshot_artifact(path)
    }


class Detector(Protocol):
    def detect(self, snapshot: RepositorySnapshot) -> DetectionResult: ...
