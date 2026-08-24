from __future__ import annotations

import json
from pathlib import Path

from ..models import DetectionResult, RepositorySnapshot
from .base import analysis_paths, read_manifest_text


class JavaScriptDetector:
    FRAMEWORKS = {
        "react": "React",
        "next": "Next.js",
        "express": "Express",
        "vite": "Vite",
    }

    def detect(self, snapshot: RepositorySnapshot) -> DetectionResult:
        result = DetectionResult()
        paths = analysis_paths(snapshot)
        manifests = sorted(path for path in paths if Path(path).name.casefold() == "package.json")
        if not manifests and not any(path.endswith((".js", ".jsx", ".ts", ".tsx")) for path in paths):
            return result
        if manifests:
            result.languages.add("JavaScript")
            result.package_managers.add("npm")
        if any(path.endswith((".js", ".jsx", ".mjs", ".cjs")) for path in paths):
            result.languages.add("JavaScript")
        if any(Path(path).name.casefold() == "tsconfig.json" for path in paths) or any(path.endswith((".ts", ".tsx")) for path in paths):
            result.languages.add("TypeScript")
        dependencies: set[str] = set()
        for manifest in manifests:
            try:
                data = json.loads(read_manifest_text(snapshot, manifest))
                if isinstance(data.get("name"), str):
                    result.project_names.append((100 if manifest == "package.json" else 60, data["name"]))
                for key in ("dependencies", "devDependencies", "peerDependencies"):
                    values = data.get(key, {})
                    if isinstance(values, dict):
                        dependencies.update(name.casefold() for name in values)
                scripts = data.get("scripts", {})
                if isinstance(scripts, dict):
                    for label in ("start", "dev"):
                        if isinstance(scripts.get(label), str):
                            result.notes.add(f"Package script `{label}` is available.")
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                result.warnings.append(f"Could not parse `{manifest}`: {type(exc).__name__}.")
        managers = {
            "pnpm-lock.yaml": "pnpm",
            "yarn.lock": "Yarn",
            "bun.lock": "Bun",
            "bun.lockb": "Bun",
        }
        for name, manager in managers.items():
            if any(Path(path).name.casefold() == name.casefold() for path in paths):
                result.package_managers.discard("npm")
                result.package_managers.add(manager)
        for dependency, framework in self.FRAMEWORKS.items():
            if dependency in dependencies:
                result.frameworks.add(framework)
        database_dependencies = {
            "pg": "PostgreSQL",
            "mysql2": "MySQL",
            "mongodb": "MongoDB",
            "redis": "Redis",
            "ioredis": "Redis",
        }
        for dependency, database in database_dependencies.items():
            if dependency in dependencies:
                result.databases.add(database)
        for dependency, framework in (("jest", "Jest"), ("vitest", "Vitest"), ("playwright", "Playwright")):
            if dependency in dependencies or f"@{dependency}/test" in dependencies:
                result.test_frameworks.add(framework)
        return result
