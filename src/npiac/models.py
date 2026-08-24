from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileInfo:
    path: str
    size: int


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    root: Path
    files: tuple[FileInfo, ...]
    is_git: bool
    warnings: tuple[str, ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(item.path for item in self.files)

    def has(self, path: str) -> bool:
        return path in self.paths


@dataclass(slots=True)
class DetectionResult:
    project_names: list[tuple[int, str]] = field(default_factory=list)
    languages: set[str] = field(default_factory=set)
    frameworks: set[str] = field(default_factory=set)
    package_managers: set[str] = field(default_factory=set)
    infrastructure: set[str] = field(default_factory=set)
    databases: set[str] = field(default_factory=set)
    test_frameworks: set[str] = field(default_factory=set)
    entry_points: dict[str, str] = field(default_factory=dict)
    notes: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "DetectionResult") -> None:
        self.project_names.extend(other.project_names)
        self.languages.update(other.languages)
        self.frameworks.update(other.frameworks)
        self.package_managers.update(other.package_managers)
        self.infrastructure.update(other.infrastructure)
        self.databases.update(other.databases)
        self.test_frameworks.update(other.test_frameworks)
        for key, value in other.entry_points.items():
            self.entry_points.setdefault(key, value)
        self.notes.update(other.notes)
        self.warnings.extend(other.warnings)


@dataclass(frozen=True, slots=True)
class ImportantFile:
    path: str
    reason: str
    score: int = 0
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AIEnrichment:
    provider: str
    model: str
    project_purpose: str
    architecture_summary: str
    key_components: tuple[str, ...]
    important_relationships: tuple[str, ...]
    coding_agent_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    project_name: str
    is_git: bool
    languages: tuple[str, ...]
    frameworks: tuple[str, ...]
    package_managers: tuple[str, ...]
    infrastructure: tuple[str, ...]
    databases: tuple[str, ...]
    test_frameworks: tuple[str, ...]
    entry_points: tuple[tuple[str, str], ...]
    test_paths: tuple[str, ...]
    config_files: tuple[str, ...]
    important_files: tuple[ImportantFile, ...]
    tree: str
    notes: tuple[str, ...]
    warnings: tuple[str, ...]
    tree_paths: tuple[str, ...] = ()
    ai_enrichment: AIEnrichment | None = None
