from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError

import pytest

from npiac.analyzer import analyze_repository
from npiac.cli import main
from npiac.constants import MAX_AI_EXCERPT_CHARS, MAX_AI_INPUT_CHARS
from npiac.enrichment import build_ai_prompt, enrich_context
from npiac.ollama import AI_RESPONSE_SCHEMA, OllamaClient, OllamaError, OllamaJSONError
from npiac.renderer import render_context


VALID_ENRICHMENT = {
    "project_purpose": "Generates compact repository guidance that helps coding agents navigate unfamiliar codebases.",
    "architecture_summary": "The analyzer orchestrates repository scanning, deterministic detectors, importance selection, and final Markdown rendering without allowing enrichment to replace detected facts.",
    "key_components": [
        "Scanner — discovers eligible repository files while enforcing ignore and safety rules.",
        "Detectors — parse ecosystem manifests and provide deterministic technology evidence.",
        "Renderer — transforms the merged repository context into stable Markdown output.",
    ],
    "important_relationships": [
        "The analyzer passes the scanner snapshot to detectors before the renderer consumes their merged findings.",
        "The analyzer invokes the renderer after selection produces a ranked repository context.",
    ],
    "coding_agent_notes": [
        "When changing detection rules, update the matching fixture and verify its golden Markdown output.",
        "Run the complete test suite after modifying selection or rendering behavior.",
    ],
}


class MockOllamaClient:
    def __init__(self, result: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.result = result or VALID_ENRICHMENT
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def generate(self, model: str, prompt: str) -> dict[str, object]:
        self.calls.append((model, prompt))
        if self.error:
            raise self.error
        return self.result


def _write(root: Path, relative: str, content: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _project(root: Path) -> None:
    _write(root, "pyproject.toml", '[project]\nname = "ai-fixture"\nversion = "0.1.0"\ndependencies = ["fastapi"]\n')
    _write(root, "src/app/main.py", "def main():\n    return 'safe'\n")
    _write(root, "src/app/services/user_service.py", "def load_user():\n    return 1\n")


def test_mocked_ollama_enriches_without_overriding_deterministic_facts(tmp_path: Path) -> None:
    _project(tmp_path)
    deterministic = analyze_repository(tmp_path)
    client = MockOllamaClient()
    enriched = enrich_context(tmp_path, deterministic, client, "test-model")

    assert replace(enriched, ai_enrichment=None) == deterministic
    assert enriched.ai_enrichment is not None
    assert client.calls[0][0] == "test-model"
    prompt = client.calls[0][1]
    assert "FastAPI" in prompt
    assert "src/app/main.py" in prompt
    assert "Probable entry point" in prompt
    assert "return 'safe'" in prompt

    rendered = render_context(enriched)
    assert "## AI Enrichment" in rendered
    assert "### Project Purpose" in rendered
    assert "### Architecture Summary" in rendered
    assert "### Key Components" in rendered
    assert "### Important Relationships" in rendered
    assert "### Notes for Coding Agents" in rendered


def test_prompt_requires_architectural_inference_and_actionable_output(tmp_path: Path) -> None:
    _project(tmp_path)
    prompt = build_ai_prompt(tmp_path, analyze_repository(tmp_path)).casefold()
    assert "infer the architecture from selected files" in prompt
    assert "explain its responsibility" in prompt
    assert "concrete call, dependency, data flow" in prompt
    assert "must be actionable" in prompt
    assert "do not repeat already-known language" in prompt
    assert "avoid vague observations" in prompt


def test_valid_enrichment_components_and_relationships_are_descriptive(tmp_path: Path) -> None:
    _project(tmp_path)
    context = enrich_context(tmp_path, analyze_repository(tmp_path), MockOllamaClient(), "quality")
    enrichment = context.ai_enrichment
    assert enrichment is not None
    assert all(len(component.split()) >= 5 for component in enrichment.key_components)
    assert all(not component.endswith((".py", ".ts", ".rs", ".cs")) for component in enrichment.key_components)
    assert all(len(relationship.split()) >= 6 for relationship in enrichment.important_relationships)
    assert all("analyzer" in relationship.casefold() for relationship in enrichment.important_relationships)


@pytest.mark.parametrize(
    ("field", "low_quality_value"),
    (
        ("project_purpose", "A repository tool."),
        (
            "architecture_summary",
            "The project has a src and tests directory and uses a standard structure for organizing source code.",
        ),
        ("key_components", ["scanner.py"]),
        ("important_relationships", ["scanner.py and renderer.py are important files"]),
        ("coding_agent_notes", ["Be careful when working with these files."]),
    ),
)
def test_low_quality_enrichment_uses_existing_fallback(
    tmp_path: Path,
    field: str,
    low_quality_value: object,
) -> None:
    _project(tmp_path)
    result = dict(VALID_ENRICHMENT)
    result[field] = low_quality_value
    context = enrich_context(tmp_path, analyze_repository(tmp_path), MockOllamaClient(result), "low-quality")
    assert context.ai_enrichment is None
    assert any("AI enrichment unavailable" in warning for warning in context.warnings)


def test_partial_quality_items_are_filtered_without_discarding_enrichment(tmp_path: Path) -> None:
    _project(tmp_path)
    partial = dict(VALID_ENRICHMENT)
    partial["key_components"] = [
        VALID_ENRICHMENT["key_components"][0],
        "scanner.py",
        VALID_ENRICHMENT["key_components"][1],
    ]
    partial["important_relationships"] = [
        "The controller calls the application service to process each repository request.",
        "scanner.py and renderer.py are related",
        "The service reads from the repository and passes data to the renderer.",
    ]
    partial["coding_agent_notes"] = [
        VALID_ENRICHMENT["coding_agent_notes"][0],
        "Be careful.",
        VALID_ENRICHMENT["coding_agent_notes"][1],
    ]

    context = enrich_context(tmp_path, analyze_repository(tmp_path), MockOllamaClient(partial), "partial")
    enrichment = context.ai_enrichment
    assert enrichment is not None
    assert len(enrichment.key_components) == 2
    assert len(enrichment.important_relationships) == 2
    assert len(enrichment.coding_agent_notes) == 2
    assert "scanner.py" not in enrichment.key_components
    assert all("are related" not in item for item in enrichment.important_relationships)
    assert "Be careful." not in enrichment.coding_agent_notes


def test_one_weak_relationship_does_not_discard_other_useful_relationships(tmp_path: Path) -> None:
    _project(tmp_path)
    partial = dict(VALID_ENRICHMENT)
    partial["important_relationships"] = [
        "The request handler invokes the analysis service before rendering repository context.",
        "The analysis service consumes scanner output and validates the merged findings.",
        "These modules work together in the project.",
    ]
    context = enrich_context(tmp_path, analyze_repository(tmp_path), MockOllamaClient(partial), "relationships")
    assert context.ai_enrichment is not None
    assert len(context.ai_enrichment.important_relationships) == 2
    assert all("work together" not in item for item in context.ai_enrichment.important_relationships)


def test_concrete_relationship_phrases_are_accepted(tmp_path: Path) -> None:
    _project(tmp_path)
    result = dict(VALID_ENRICHMENT)
    result["important_relationships"] = [
        "The controller calls the analysis service to handle each incoming repository request.",
        "The command invokes the scanner before any detector evaluates repository evidence.",
        "The renderer consumes the ranked context and produces the final Markdown document.",
        "The enrichment layer integrates with Ollama after deterministic analysis has completed.",
        "The scanner passes data to detectors before importance selection begins its ranking pass.",
        "The renderer renders the merged context into a stable section-oriented Markdown document.",
        "The validator validates model output before enrichment is attached to deterministic context.",
        "The analyzer reads from the scanner snapshot when coordinating ecosystem-specific detectors.",
        "The CLI writes to the selected output file only after rendering has completed.",
    ]
    context = enrich_context(tmp_path, analyze_repository(tmp_path), MockOllamaClient(result), "phrases")
    assert context.ai_enrichment is not None
    assert len(context.ai_enrichment.important_relationships) == 9


@pytest.mark.parametrize(
    ("field", "weak_item"),
    (
        ("key_components", "scanner.py"),
        ("important_relationships", "The modules work together."),
        ("coding_agent_notes", "Be careful."),
    ),
)
def test_enrichment_falls_back_when_fewer_than_two_useful_list_items_remain(
    tmp_path: Path,
    field: str,
    weak_item: str,
) -> None:
    _project(tmp_path)
    result = dict(VALID_ENRICHMENT)
    result[field] = [VALID_ENRICHMENT[field][0], weak_item]
    context = enrich_context(tmp_path, analyze_repository(tmp_path), MockOllamaClient(result), "threshold")
    assert context.ai_enrichment is None
    assert any("AI enrichment unavailable" in warning for warning in context.warnings)


def test_prompt_enforces_ignore_secret_binary_and_size_limits(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path, ".repocontextignore", "src/services/ignored_service.py\n")
    _write(tmp_path, "src/services/ignored_service.py", "IGNORED_SECRET = 'do-not-send'\n")
    _write(
        tmp_path,
        "src/services/large_service.py",
        "SAFE_MARKER = True\nAPI_KEY = 'super-secret-value'\nTOKEN = 'another-secret'\n"
        + "A" * (MAX_AI_EXCERPT_CHARS * 3),
    )
    binary = tmp_path / "src" / "routes" / "binary.py"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"BINARY_SECRET\x00more")
    _write(tmp_path, ".env", "PASSWORD=env-secret")
    _write(tmp_path, "credentials.py", "PASSWORD='credential-secret'")
    _write(tmp_path, "private.pem", "PRIVATE KEY")
    _write(tmp_path, "package-lock.json", '{"token":"lock-secret"}')

    context = analyze_repository(tmp_path)
    prompt = build_ai_prompt(tmp_path, context)

    assert len(prompt) <= MAX_AI_INPUT_CHARS
    assert "SAFE_MARKER" in prompt
    assert "super-secret-value" not in prompt
    assert "another-secret" not in prompt
    assert "[REDACTED SENSITIVE LINE]" in prompt
    assert "do-not-send" not in prompt
    assert "ignored_service.py" not in prompt
    assert "BINARY_SECRET" not in prompt
    assert "env-secret" not in prompt
    assert "credential-secret" not in prompt
    assert "lock-secret" not in prompt
    assert prompt.count("A") <= MAX_AI_EXCERPT_CHARS


def test_total_prompt_limit_with_many_selected_sources(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name":"large-ai-input"}')
    for index in range(40):
        _write(tmp_path, f"src/services/service_{index:02}.ts", "export const value = '" + "x" * 3_000 + "';")
    prompt = build_ai_prompt(tmp_path, analyze_repository(tmp_path))
    assert len(prompt) <= MAX_AI_INPUT_CHARS


def test_ollama_unavailable_keeps_deterministic_output_with_warning(tmp_path: Path) -> None:
    _project(tmp_path)
    deterministic = analyze_repository(tmp_path)
    enriched = enrich_context(
        tmp_path,
        deterministic,
        MockOllamaClient(error=OllamaError("model not found")),
        "missing-model",
    )
    assert enriched.ai_enrichment is None
    assert enriched.languages == deterministic.languages
    rendered = render_context(enriched)
    assert "## AI Enrichment" not in rendered
    assert "AI enrichment unavailable from Ollama model `missing-model`" in rendered


def test_invalid_ollama_payload_falls_back_to_warning(tmp_path: Path) -> None:
    _project(tmp_path)
    context = enrich_context(tmp_path, analyze_repository(tmp_path), MockOllamaClient({"project_purpose": "only"}), "bad")
    assert context.ai_enrichment is None
    assert any("AI enrichment unavailable" in warning for warning in context.warnings)


def test_ollama_client_uses_generate_endpoint_and_structured_nonstreaming_request() -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit: int) -> bytes:
            captured["read_limit"] = limit
            return json.dumps({"response": json.dumps(VALID_ENRICHMENT)}).encode("utf-8")

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    result = OllamaClient("localhost:11434/", opener=opener).generate("mock-model", "prompt")
    assert result == VALID_ENRICHMENT
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["payload"]["model"] == "mock-model"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["format"] == AI_RESPONSE_SCHEMA


def test_debug_logs_http_status_and_redacted_raw_model_response() -> None:
    diagnostics: list[str] = []
    response_payload = dict(VALID_ENRICHMENT)
    response_payload["project_purpose"] = (
        "Generates compact repository guidance while PASSWORD=excluded-secret remains private."
    )
    response_payload["token"] = "json-secret-value"

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit: int) -> bytes:
            return json.dumps({"response": json.dumps(response_payload)}).encode("utf-8")

    result = OllamaClient(opener=lambda request, timeout: FakeResponse(), diagnostic=diagnostics.append).generate(
        "mock", "prompt"
    )
    assert result == response_payload
    joined = "\n".join(diagnostics)
    assert "Ollama HTTP status: 200" in joined
    assert "Raw model response before parsing:" in joined
    assert "[REDACTED]" in joined
    assert "excluded-secret" not in joined
    assert "json-secret-value" not in joined


def test_debug_logs_json_parse_error() -> None:
    diagnostics: list[str] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit: int) -> bytes:
            return json.dumps({"response": "not-json"}).encode("utf-8")

    client = OllamaClient(opener=lambda request, timeout: FakeResponse(), diagnostic=diagnostics.append)
    with pytest.raises(OllamaJSONError):
        client.generate("mock", "prompt")
    joined = "\n".join(diagnostics)
    assert "Raw model response before parsing: not-json" in joined
    assert "JSON parse error: model output" in joined


def test_debug_logs_http_error_status() -> None:
    diagnostics: list[str] = []

    def opener(request, timeout):
        raise HTTPError(request.full_url, 404, "model not found", {}, None)

    with pytest.raises(OllamaError):
        OllamaClient(opener=opener, diagnostic=diagnostics.append).generate("missing", "prompt")
    assert "Ollama HTTP status: 404" in diagnostics


def test_debug_logs_schema_validation_error(tmp_path: Path) -> None:
    _project(tmp_path)
    diagnostics: list[str] = []
    invalid = dict(VALID_ENRICHMENT)
    invalid.pop("architecture_summary")
    context = enrich_context(
        tmp_path,
        analyze_repository(tmp_path),
        MockOllamaClient(invalid),
        "schema-error",
        diagnostic=diagnostics.append,
    )
    assert context.ai_enrichment is None
    assert any("Schema validation error: missing required fields: architecture_summary" in item for item in diagnostics)


def test_debug_logs_quality_validation_rejection(tmp_path: Path) -> None:
    _project(tmp_path)
    diagnostics: list[str] = []
    invalid = dict(VALID_ENRICHMENT)
    invalid["key_components"] = ["scanner.py", "renderer.py"]
    context = enrich_context(
        tmp_path,
        analyze_repository(tmp_path),
        MockOllamaClient(invalid),
        "quality-error",
        diagnostic=diagnostics.append,
    )
    assert context.ai_enrichment is None
    assert any("Quality validation filtered key_components[0]" in item for item in diagnostics)
    assert any("Quality validation rejection: key_components has only 0 useful item" in item for item in diagnostics)


def test_cli_ai_uses_mocked_client_and_no_ai_does_not(monkeypatch, tmp_path: Path, capsys) -> None:
    _project(tmp_path)
    client = MockOllamaClient()
    base_urls: list[str] = []

    def client_factory(base_url: str):
        base_urls.append(base_url)
        return client

    monkeypatch.setattr("npiac.cli.OllamaClient", client_factory)

    assert main([
        str(tmp_path),
        "--ai",
        "--provider",
        "ollama",
        "--model",
        "mock",
        "--ollama-base-url",
        "http://127.0.0.1:9999",
        "--stdout",
    ]) == 0
    ai_output = capsys.readouterr().out
    assert "## AI Enrichment" in ai_output
    assert client.calls
    assert base_urls == ["http://127.0.0.1:9999"]

    client.calls.clear()
    assert main([str(tmp_path), "--model", "ignored", "--stdout"]) == 0
    deterministic_output = capsys.readouterr().out
    assert "## AI Enrichment" not in deterministic_output
    assert not client.calls


def test_cli_ai_failure_still_succeeds_with_warning(monkeypatch, tmp_path: Path, capsys) -> None:
    _project(tmp_path)
    client = MockOllamaClient(error=OllamaError("connection refused"))
    monkeypatch.setattr("npiac.cli.OllamaClient", lambda base_url: client)
    assert main([str(tmp_path), "--ai", "--model", "unavailable", "--stdout"]) == 0
    output = capsys.readouterr().out
    assert "## AI Enrichment" not in output
    assert "AI enrichment unavailable from Ollama model `unavailable`" in output


def test_debug_ai_flag_writes_diagnostics_only_to_stderr(monkeypatch, tmp_path: Path, capsys) -> None:
    _project(tmp_path)
    invalid = dict(VALID_ENRICHMENT)
    invalid["important_relationships"] = ["scanner.py and renderer.py", "modules work together"]
    client = MockOllamaClient(invalid)
    monkeypatch.setattr(
        "npiac.cli.OllamaClient",
        lambda base_url, diagnostic=None: client,
    )
    assert main([str(tmp_path), "--ai", "--debug-ai", "--model", "debug", "--stdout"]) == 0
    captured = capsys.readouterr()
    assert "AI enrichment unavailable" in captured.out
    assert "npiac AI debug: Quality validation rejection:" in captured.err

    assert main([str(tmp_path), "--ai", "--model", "normal", "--stdout"]) == 0
    normal = capsys.readouterr()
    assert "AI enrichment unavailable" in normal.out
    assert normal.err == ""
