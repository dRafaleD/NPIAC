from __future__ import annotations

from pathlib import Path

from ..models import DetectionResult, RepositorySnapshot
from .base import analysis_paths


class GenericDetector:
    EXTENSIONS = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".rs": "Rust",
        ".cs": "C#",
    }

    def detect(self, snapshot: RepositorySnapshot) -> DetectionResult:
        result = DetectionResult(project_names=[(0, snapshot.root.name)])
        paths = analysis_paths(snapshot)
        for path in paths:
            language = self.EXTENSIONS.get(Path(path).suffix.casefold())
            if language:
                result.languages.add(language)
        lowered = {path.casefold() for path in paths}
        if any(
            path == "dockerfile"
            or path.endswith("/dockerfile")
            or Path(path).name in {"compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"}
            for path in lowered
        ):
            result.infrastructure.add("Docker")
        if any(path.startswith(".github/workflows/") for path in lowered):
            result.infrastructure.add("GitHub Actions")
        if any(path.endswith(".tf") for path in lowered):
            result.infrastructure.add("Terraform")
        if any(path.endswith("chart.yaml") for path in lowered):
            result.infrastructure.add("Helm")
        return result
