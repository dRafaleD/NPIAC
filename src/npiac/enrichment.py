from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from .constants import (
    AI_SOURCE_SUFFIXES,
    LOCKFILE_NAMES,
    MAX_AI_EXCERPT_CHARS,
    MAX_AI_IMPORTANT_FILES_CHARS,
    MAX_AI_INPUT_CHARS,
    MAX_AI_TREE_CHARS,
    SENSITIVE_NAMES,
    SENSITIVE_SUFFIXES,
)
from .models import AIEnrichment, RepositoryContext
from .ollama import Diagnostic, OllamaJSONError, OllamaQualityError, OllamaSchemaError, safe_debug_text


class EnrichmentClient(Protocol):
    def generate(self, model: str, prompt: str) -> dict[str, object]: ...


SENSITIVE_LINE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|secret|password|passwd|private[_-]?key|credential|token|authorization|bearer|connection[_-]?string|dsn)"
)

COMPONENT_RESPONSIBILITY = re.compile(
    r"(?i)\b(handles?|discovers?|scans?|detects?|selects?|ranks?|renders?|coordinates?|validates?|parses?|loads?|stores?|exposes?|manages?|orchestrates?|builds?|generates?|provides?|transforms?|filters?|owns?|implements?)\b"
)
RELATIONSHIP_SIGNAL = re.compile(
    r"(?i)(?:->|→|\b(calls?|feeds?|uses?|produces?|consumes?|depends on|invokes?|integrates? with|pass(?:es)?(?: data)? to|routes?|maps?|validates?|reads?(?: from)?|writes?(?: to)?|coordinates?|renders?|imports?|delegates?|provides? .* to)\b)"
)
ACTION_SIGNAL = re.compile(
    r"(?i)\b(add|avoid|check|extend|inspect|keep|modify|preserve|regenerate|review|run|start|test|trace|treat|update|use|verify)\b"
)
BARE_FILENAME = re.compile(r"^[\w./\\-]+\.(?:py|js|jsx|ts|tsx|rs|cs)$", re.IGNORECASE)


def _safe_source_path(path: str, context: RepositoryContext) -> bool:
    name = Path(path).name.casefold()
    return (
        path in context.tree_paths
        and Path(path).suffix.casefold() in AI_SOURCE_SUFFIXES
        and name not in LOCKFILE_NAMES
        and name not in SENSITIVE_NAMES
        and not name.startswith((".env.", "credentials."))
        and not name.endswith(SENSITIVE_SUFFIXES)
    )


def _safe_excerpt(root: Path, path: str) -> str | None:
    root = root.resolve()
    candidate = root / Path(path)
    try:
        if candidate.is_symlink():
            return None
        full_path = candidate.resolve()
        if not full_path.is_relative_to(root) or not full_path.is_file():
            return None
        with full_path.open("rb") as handle:
            raw = handle.read(MAX_AI_EXCERPT_CHARS * 4 + 1)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    safe_lines = ["[REDACTED SENSITIVE LINE]" if SENSITIVE_LINE.search(line) else line for line in text.splitlines()]
    excerpt = "\n".join(safe_lines)
    if len(excerpt) > MAX_AI_EXCERPT_CHARS:
        excerpt = excerpt[: MAX_AI_EXCERPT_CHARS - 16].rstrip() + "\n...[truncated]"
    return excerpt


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 16)].rstrip() + "\n...[truncated]"


def build_ai_prompt(root: Path, context: RepositoryContext) -> str:
    technologies = sorted(
        set(
            (*context.languages, *context.frameworks, *context.package_managers, *context.infrastructure, *context.databases)
        ),
        key=str.casefold,
    )
    important_lines = [
        f"- {item.path} | score={item.score} | reasons={'; '.join(item.reasons or (item.reason,))}"
        for item in context.important_files
    ]
    sections = [
        "You enrich deterministic repository analysis after it has completed. The deterministic findings are the source "
        "of truth: do not revise, override, or contradict them. Return only the five requested JSON fields and no prose "
        "outside the JSON object. Base every claim on selected paths, module names, reasons, and safe excerpts; state "
        "uncertainty briefly when evidence is incomplete.",
        "QUALITY REQUIREMENTS:\n"
        "- Infer the architecture from selected files, module boundaries, conventional paths, and names; explain the likely "
        "control/data flow rather than paraphrasing the tree.\n"
        "- project_purpose: 1-2 concise sentences describing the concrete problem or workflow the project supports.\n"
        "- architecture_summary: 2-4 concise sentences explaining boundaries, orchestration, and data/control flow.\n"
        "- key_components: each item must name a logical component and explain its responsibility. Never return a bare "
        "filename or directory name.\n"
        "- important_relationships: each item must describe a concrete call, dependency, data flow, ownership, or sequencing "
        "relationship between named components.\n"
        "- coding_agent_notes: each item must be actionable: say where to start, what to preserve or change, and what to test "
        "or verify.\n"
        "- Do not repeat already-known language, framework, or package-manager metadata unless it directly explains an "
        "architectural decision.\n"
        "- Avoid vague observations such as 'the project has a src and tests directory', 'uses a standard structure', or "
        "'contains several components'.\n"
        "- Be concise: provide at least 2 and preferably 2-8 high-information items per list; omit unsupported speculation.",
        f"PROJECT: {context.project_name}",
        "DETECTED TECHNOLOGIES:\n" + ("\n".join(f"- {item}" for item in technologies) or "- None detected"),
        "REPOSITORY TREE:\n" + _bounded(context.tree, MAX_AI_TREE_CHARS),
        "SELECTED IMPORTANT FILES:\n"
        + _bounded("\n".join(important_lines) or "- None selected", MAX_AI_IMPORTANT_FILES_CHARS),
    ]
    prompt = "\n\n".join(sections)
    excerpt_blocks: list[str] = []
    for item in context.important_files:
        if not _safe_source_path(item.path, context):
            continue
        excerpt = _safe_excerpt(root, item.path)
        if not excerpt:
            continue
        block = f"FILE: {item.path}\n```text\n{excerpt}\n```"
        candidate = prompt + "\n\nSAFE SOURCE EXCERPTS:\n" + "\n\n".join((*excerpt_blocks, block))
        if len(candidate) > MAX_AI_INPUT_CHARS:
            break
        excerpt_blocks.append(block)
    if excerpt_blocks:
        prompt += "\n\nSAFE SOURCE EXCERPTS:\n" + "\n\n".join(excerpt_blocks)
    return _bounded(prompt, MAX_AI_INPUT_CHARS)


def _clean_text(value: object, limit: int = 1_200) -> str:
    if not isinstance(value, str):
        raise OllamaSchemaError("enrichment field has an invalid type")
    cleaned = " ".join(value.split()).replace("`", "'")[:limit].strip()
    cleaned = re.sub(r"^(?:#{1,6}|>|[-*+]\s+)", "", cleaned).strip()
    if not cleaned:
        raise OllamaQualityError("enrichment field is empty")
    return cleaned


def _word_count(value: str) -> int:
    return len(re.findall(r"\b\w+\b", value, flags=re.UNICODE))


def _nontrivial_summary(value: object, field_name: str, minimum_words: int, minimum_chars: int) -> str:
    cleaned = _clean_text(value)
    vague = (
        "has a src and tests directory",
        "uses a standard structure",
        "contains several components",
    )
    if len(cleaned) < minimum_chars or _word_count(cleaned) < minimum_words:
        raise OllamaQualityError(f"{field_name} is too superficial")
    if any(phrase in cleaned.casefold() for phrase in vague):
        raise OllamaQualityError(f"{field_name} is vague")
    return cleaned


def _item_quality_issue(item: str, field_name: str) -> str | None:
    if field_name == "key_components":
        descriptive_separator = ":" in item or " — " in item or " - " in item
        if BARE_FILENAME.fullmatch(item) or len(item) < 25 or _word_count(item) < 5:
            return "lacks a meaningful responsibility"
        if not descriptive_separator and not COMPONENT_RESPONSIBILITY.search(item):
            return "lacks a responsibility description"
    elif field_name == "important_relationships":
        if len(item) < 35 or _word_count(item) < 6 or not RELATIONSHIP_SIGNAL.search(item):
            return "lacks a concrete interaction"
    elif field_name == "coding_agent_notes":
        if len(item) < 30 or _word_count(item) < 5 or not ACTION_SIGNAL.search(item):
            return "is not actionable"
    return None


def _clean_list(
    value: object,
    field_name: str,
    diagnostic: Diagnostic | None = None,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OllamaSchemaError(f"{field_name} has an invalid type")
    accepted: list[str] = []
    for index, entry in enumerate(value[:12]):
        try:
            item = _clean_text(entry, 400)
            issue = _item_quality_issue(item, field_name)
        except OllamaQualityError as exc:
            issue = str(exc)
            item = ""
        if issue is not None:
            _diagnose(diagnostic, f"Quality validation filtered {field_name}[{index}]: {issue}")
            continue
        accepted.append(item)
    if len(accepted) < 2:
        raise OllamaQualityError(
            f"{field_name} has only {len(accepted)} useful item(s); at least 2 are required"
        )
    return tuple(accepted)


def _validate_schema(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        raise OllamaSchemaError("top-level model output must be a JSON object")
    string_fields = {"project_purpose": 500, "architecture_summary": 800}
    list_fields = {"key_components", "important_relationships", "coding_agent_notes"}
    required = set(string_fields) | list_fields
    missing = sorted(required - set(result))
    unexpected = sorted(set(result) - required)
    if missing:
        raise OllamaSchemaError("missing required fields: " + ", ".join(missing))
    if unexpected:
        raise OllamaSchemaError("unexpected fields: " + ", ".join(unexpected))
    for field_name, maximum in string_fields.items():
        value = result[field_name]
        if not isinstance(value, str):
            raise OllamaSchemaError(f"{field_name} must be a string")
        if len(value) > maximum:
            raise OllamaSchemaError(f"{field_name} exceeds {maximum} characters")
    for field_name in sorted(list_fields):
        value = result[field_name]
        if not isinstance(value, list):
            raise OllamaSchemaError(f"{field_name} must be an array")
        if not 2 <= len(value) <= 12:
            raise OllamaSchemaError(f"{field_name} must contain 2 to 12 items")
        for index, item in enumerate(value):
            if not isinstance(item, str):
                raise OllamaSchemaError(f"{field_name}[{index}] must be a string")
            if len(item) > 400:
                raise OllamaSchemaError(f"{field_name}[{index}] exceeds 400 characters")
    return result


def _diagnose(diagnostic: Diagnostic | None, message: str) -> None:
    if diagnostic is not None:
        diagnostic(safe_debug_text(message))


def enrich_context(
    root: Path,
    context: RepositoryContext,
    client: EnrichmentClient,
    model: str,
    diagnostic: Diagnostic | None = None,
) -> RepositoryContext:
    display_model = " ".join(model.split()).replace("`", "'")[:100]
    warning = f"AI enrichment unavailable from Ollama model `{display_model}`; deterministic analysis was used."
    try:
        result = _validate_schema(client.generate(model, build_ai_prompt(root, context)))
        enrichment = AIEnrichment(
            provider="ollama",
            model=display_model,
            project_purpose=_nontrivial_summary(result.get("project_purpose"), "project purpose", 5, 30),
            architecture_summary=_nontrivial_summary(result.get("architecture_summary"), "architecture summary", 8, 45),
            key_components=_clean_list(result.get("key_components"), "key_components", diagnostic),
            important_relationships=_clean_list(result.get("important_relationships"), "important_relationships", diagnostic),
            coding_agent_notes=_clean_list(result.get("coding_agent_notes"), "coding_agent_notes", diagnostic),
        )
        return replace(context, ai_enrichment=enrichment)
    except OllamaJSONError as exc:
        _diagnose(diagnostic, f"JSON parse error: {exc}")
    except OllamaSchemaError as exc:
        _diagnose(diagnostic, f"Schema validation error: {exc}")
    except OllamaQualityError as exc:
        _diagnose(diagnostic, f"Quality validation rejection: {exc}")
    except Exception as exc:
        _diagnose(diagnostic, f"Ollama enrichment error: {type(exc).__name__}")
    warnings = tuple(sorted(set((*context.warnings, warning)), key=str.casefold))
    return replace(context, warnings=warnings, ai_enrichment=None)
