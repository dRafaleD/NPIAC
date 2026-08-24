from __future__ import annotations

import tomllib
from pathlib import Path

from ..models import DetectionResult, RepositorySnapshot
from .base import analysis_paths


class RustDetector:
    FRAMEWORKS = {"tokio": "Tokio", "axum": "Axum"}

    def detect(self, snapshot: RepositorySnapshot) -> DetectionResult:
        result = DetectionResult()
        paths = analysis_paths(snapshot)
        manifests = sorted(path for path in paths if Path(path).name.casefold() == "cargo.toml")
        if not manifests and not any(path.endswith(".rs") for path in paths):
            return result
        result.languages.add("Rust")
        if not manifests:
            return result
        result.package_managers.add("Cargo")
        for manifest in manifests:
            try:
                data = tomllib.loads((snapshot.root / manifest).read_text(encoding="utf-8"))
                package = data.get("package", {})
                if isinstance(package, dict) and isinstance(package.get("name"), str):
                    result.project_names.append((100 if manifest == "Cargo.toml" else 60, package["name"]))
                dependencies = set()
                for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                    values = data.get(key, {})
                    if isinstance(values, dict):
                        dependencies.update(name.casefold() for name in values)
                for dependency, framework in self.FRAMEWORKS.items():
                    if dependency in dependencies:
                        result.frameworks.add(framework)
                if dependencies & {"diesel", "sqlx"}:
                    result.databases.add("SQL database")
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                result.warnings.append(f"Could not parse `{manifest}`: {type(exc).__name__}.")
        return result
