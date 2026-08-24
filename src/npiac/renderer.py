from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from .constants import GENERATED_MARKER, MANIFEST_NAMES, MAX_TREE_ENTRIES
from .models import RepositoryContext
from .selectors import render_tree


def _bullet_list(values: Iterable[str]) -> list[str]:
    return [f"- {value}" for value in values]


TRIM_WARNING = "Content was trimmed to fit the requested budget."
AI_WARNING_PREFIX = "AI enrichment unavailable from Ollama"


def _render_full(context: RepositoryContext) -> str:
    lines = [
        GENERATED_MARKER,
        "# Repository Context",
        "",
        "> Generated deterministically by NPIAC.",
        "",
        "## Overview",
        "",
        f"- Project name: {context.project_name}",
        f"- Repository type: {'Git' if context.is_git else 'Directory'}",
        f"- Languages: {', '.join(context.languages) if context.languages else 'None detected'}",
    ]

    if context.frameworks or context.package_managers or context.infrastructure or context.databases:
        lines.extend(["", "## Technologies"])
        sections = (
            ("Frameworks and libraries", context.frameworks),
            ("Package and build tools", context.package_managers),
            ("Infrastructure", context.infrastructure),
            ("Data", context.databases),
        )
        for heading, values in sections:
            if values:
                lines.extend(["", f"### {heading}", "", *_bullet_list(values)])

    lines.extend(["", "## Repository Structure", "", "```text", context.tree, "```"])

    if context.important_files:
        lines.extend(["", "## Important Files", ""])
        lines.extend(f"- `{item.path}` — {item.reason}" for item in context.important_files)

    if context.entry_points:
        lines.extend(["", "## Entry Points", ""])
        lines.extend(f"- {label}: `{path}`" for label, path in context.entry_points)

    if context.test_paths or context.test_frameworks:
        lines.extend(["", "## Tests", ""])
        if context.test_paths:
            lines.append("- Paths: " + ", ".join(f"`{path}`" for path in context.test_paths))
        if context.test_frameworks:
            lines.append("- Frameworks: " + ", ".join(context.test_frameworks))

    if context.config_files:
        lines.extend(["", "## Configuration", "", *_bullet_list(f"`{path}`" for path in context.config_files)])

    if context.notes:
        lines.extend(["", "## Detection Notes", "", *_bullet_list(context.notes)])

    if context.ai_enrichment is not None:
        enrichment = context.ai_enrichment
        lines.extend(
            [
                "",
                "## AI Enrichment",
                "",
                f"> Generated locally with Ollama model `{enrichment.model}`. Deterministic findings remain the source of truth.",
                "",
                "### Project Purpose",
                "",
                enrichment.project_purpose,
                "",
                "### Architecture Summary",
                "",
                enrichment.architecture_summary,
            ]
        )
        enrichment_sections = (
            ("Key Components", enrichment.key_components),
            ("Important Relationships", enrichment.important_relationships),
            ("Notes for Coding Agents", enrichment.coding_agent_notes),
        )
        for heading, values in enrichment_sections:
            if values:
                lines.extend(["", f"### {heading}", "", *_bullet_list(values)])

    if context.warnings:
        lines.extend(["", "## Warnings", "", *_bullet_list(context.warnings)])

    return "\n".join(lines) + "\n"


def _path_priority(context: RepositoryContext, path: str) -> tuple[int, str, str]:
    name = Path(path).name.casefold()
    entry_paths = {entry_path for _, entry_path in context.entry_points}
    important = {item.path: item.score for item in context.important_files}
    if path in entry_paths:
        priority = 1_000
    elif name in MANIFEST_NAMES or name.endswith((".csproj", ".sln")):
        priority = 900
    elif path in important:
        priority = 700 + min(199, max(0, important[path] // 10))
    elif path in context.config_files:
        priority = 500
    elif path in context.test_paths:
        priority = 300
    else:
        priority = 0
    return (priority, path.casefold(), path)


def _fits(context: RepositoryContext, budget: int) -> str | None:
    rendered = _render_full(context)
    return rendered if len(rendered) <= budget else None


def _minimal_trimmed_output(budget: int) -> str:
    candidates = (
        "# Repository Context\n\n> Content trimmed to budget.\n",
        "> Content trimmed.\n",
        "> Trimmed.\n",
        "TRIMMED\n",
    )
    for candidate in candidates:
        if len(candidate) <= budget:
            return candidate
    return "!TRIMMED"[:budget]


def _render_budgeted(context: RepositoryContext, budget: int) -> str:
    original_warnings = tuple(warning for warning in context.warnings if warning != TRIM_WARNING)
    state = replace(context, warnings=tuple(sorted((*original_warnings, TRIM_WARNING), key=str.casefold)))
    rendered = _fits(state, budget)
    if rendered is not None:
        return rendered

    def update(**changes: object) -> str | None:
        nonlocal state
        state = replace(state, **changes)
        return _fits(state, budget)

    # Detection notes and ordinary warnings are useful, but less important than project facts.
    if state.notes:
        rendered = update(notes=())
        if rendered is not None:
            return rendered
    if state.ai_enrichment is not None:
        rendered = update(ai_enrichment=None)
        if rendered is not None:
            return rendered
    if original_warnings:
        persistent_warnings = tuple(
            warning for warning in original_warnings if warning.startswith(AI_WARNING_PREFIX)
        )
        rendered = update(warnings=tuple(sorted((*persistent_warnings, TRIM_WARNING), key=str.casefold)))
        if rendered is not None:
            return rendered

    # Remove low-priority tree paths first. Manifests and entry points survive this pass.
    selected_paths = set(state.tree_paths)
    protected_paths = {
        path
        for path in selected_paths
        if _path_priority(state, path)[0] >= 700
    }
    ordered_paths = sorted(selected_paths, key=lambda path: _path_priority(state, path), reverse=True)
    selected_paths = protected_paths | set(ordered_paths[:MAX_TREE_ENTRIES])
    rendered = update(tree=render_tree(selected_paths))
    if rendered is not None:
        return rendered
    removable_paths = sorted(
        selected_paths - protected_paths,
        key=lambda path: _path_priority(state, path),
    )
    for path in removable_paths:
        selected_paths.remove(path)
        rendered = update(tree=render_tree(selected_paths))
        if rendered is not None:
            return rendered

    # Then trim lower-priority metadata, one deterministic group at a time.
    for field_name in ("infrastructure", "databases", "test_paths", "test_frameworks"):
        if getattr(state, field_name):
            rendered = update(**{field_name: ()})
            if rendered is not None:
                return rendered

    manifest_paths = {
        path
        for path in state.config_files
        if Path(path).name.casefold() in MANIFEST_NAMES or path.casefold().endswith((".csproj", ".sln"))
    }
    reduced_configs = tuple(path for path in state.config_files if path in manifest_paths)
    if reduced_configs != state.config_files:
        rendered = update(config_files=reduced_configs)
        if rendered is not None:
            return rendered

    entry_paths = {path for _, path in state.entry_points}
    reduced_important = tuple(
        item
        for item in state.important_files
        if item.path in entry_paths
        or Path(item.path).name.casefold() in MANIFEST_NAMES
        or item.path.casefold().endswith((".csproj", ".sln"))
    )
    if reduced_important != state.important_files:
        rendered = update(important_files=reduced_important)
        if rendered is not None:
            return rendered

    for field_name in ("frameworks", "package_managers"):
        if getattr(state, field_name):
            rendered = update(**{field_name: ()})
            if rendered is not None:
                return rendered

    # Protected paths and facts are only removed for genuinely tiny budgets.
    for path in sorted(protected_paths, key=lambda value: _path_priority(state, value)):
        selected_paths.remove(path)
        rendered = update(tree=render_tree(selected_paths))
        if rendered is not None:
            return rendered
    for field_name in ("config_files", "important_files", "entry_points", "languages"):
        if getattr(state, field_name):
            rendered = update(**{field_name: ()})
            if rendered is not None:
                return rendered
    return _minimal_trimmed_output(budget)


def render_context(context: RepositoryContext, budget: int | None = None) -> str:
    """Render context, optionally limiting the result to a character budget."""
    rendered = _render_full(context)
    if budget is None or len(rendered) <= budget:
        return rendered
    if budget < 1:
        raise ValueError("Budget must be a positive integer.")
    return _render_budgeted(context, budget)
