from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ..models import DetectionResult, RepositorySnapshot
from .base import analysis_paths, read_manifest_text


def _flatten_dependencies(data: dict) -> set[str]:
    dependencies: list[str] = []
    project = data.get("project", {})
    if isinstance(project, dict):
        dependencies.extend(project.get("dependencies", []) or [])
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for values in optional.values():
                if isinstance(values, list):
                    dependencies.extend(values)
    tool = data.get("tool", {})
    if isinstance(tool, dict):
        poetry = tool.get("poetry", {})
        if isinstance(poetry, dict):
            dependencies.extend((poetry.get("dependencies", {}) or {}).keys())
            dependencies.extend((poetry.get("group", {}) or {}).keys())
    return {_dependency_name(item) for item in dependencies if isinstance(item, str)}


def _dependency_name(value: str) -> str:
    return re.split(r"[\s<>=!~\[;]", value.strip(), maxsplit=1)[0].casefold().replace("_", "-")


class PythonDetector:
    FRAMEWORKS = {
        "fastapi": "FastAPI",
        "flask": "Flask",
        "django": "Django",
    }

    def detect(self, snapshot: RepositorySnapshot) -> DetectionResult:
        result = DetectionResult()
        paths = analysis_paths(snapshot)
        pyprojects = sorted(path for path in paths if Path(path).name.casefold() == "pyproject.toml")
        requirement_files = sorted(
            path
            for path in paths
            if Path(path).name.casefold() == "requirements.txt"
            or Path(path).name.casefold().startswith("requirements") and path.casefold().endswith(".txt")
        )
        if not (pyprojects or requirement_files or any(path.endswith(".py") for path in paths)):
            return result
        result.languages.add("Python")
        dependencies: set[str] = set()
        for manifest in pyprojects:
            result.package_managers.add("pip")
            try:
                data = tomllib.loads(read_manifest_text(snapshot, manifest))
                base = Path(manifest).parent.as_posix()
                prefix = "" if base == "." else base + "/"
                name_priority = 100 if manifest == "pyproject.toml" else 60
                project = data.get("project", {})
                if isinstance(project, dict) and isinstance(project.get("name"), str):
                    result.project_names.append((name_priority, project["name"]))
                scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
                if isinstance(scripts, dict):
                    for script_name, target in sorted(scripts.items()):
                        if not isinstance(target, str):
                            continue
                        module = target.split(":", 1)[0].replace(".", "/") + ".py"
                        for candidate in (f"{prefix}src/{module}", f"{prefix}{module}"):
                            if candidate in paths:
                                result.entry_points.setdefault(f"CLI `{script_name}`", candidate)
                                break
                poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
                if isinstance(poetry, dict) and isinstance(poetry.get("name"), str):
                    result.project_names.append((name_priority - 10, poetry["name"]))
                dependencies.update(_flatten_dependencies(data))
                if isinstance(poetry, dict) and poetry:
                    result.package_managers.add("Poetry")
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                result.warnings.append(f"Could not parse `{manifest}`: {type(exc).__name__}.")
        for path in requirement_files:
            result.package_managers.add("pip")
            try:
                for line in read_manifest_text(snapshot, path).splitlines():
                    line = line.strip()
                    if line and not line.startswith(("#", "-")):
                        dependencies.add(_dependency_name(line))
            except (OSError, UnicodeError):
                result.warnings.append(f"Could not parse `{path}`.")
        lock_managers = {"uv.lock": "uv", "pdm.lock": "PDM", "Pipfile.lock": "Pipenv"}
        for file_name, manager in lock_managers.items():
            if any(Path(path).name.casefold() == file_name.casefold() for path in paths):
                result.package_managers.add(manager)
        for dependency, framework in self.FRAMEWORKS.items():
            if dependency in dependencies:
                result.frameworks.add(framework)
        if "pytest" in dependencies or any(path.casefold().endswith("tests/conftest.py") for path in paths):
            result.test_frameworks.add("pytest")
        if dependencies & {"sqlalchemy", "psycopg", "psycopg2", "asyncpg"}:
            result.databases.add("PostgreSQL" if dependencies & {"psycopg", "psycopg2", "asyncpg"} else "SQL database")
        return result
