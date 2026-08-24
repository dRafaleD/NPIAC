from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .constants import MAX_AI_RESPONSE_BYTES


class OllamaError(RuntimeError):
    """A stable, user-safe Ollama failure."""


class OllamaJSONError(OllamaError):
    """Ollama returned content that could not be parsed as JSON."""


class OllamaSchemaError(OllamaError):
    """Ollama returned JSON that does not match the enrichment schema."""


class OllamaQualityError(OllamaError):
    """Ollama returned structurally valid but low-quality enrichment."""


Diagnostic = Callable[[str], None]

_DEBUG_SECRET_VALUE = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?key|token|credential|private[_-]?key|authorization|dsn)\b"
    r"(\s*(?:is|=|:)\s*[\\\"']?)([^\\\"',;\s}\]]+)"
)
_DEBUG_JSON_SECRET = re.compile(
    r"(?i)([\"'](?:password|passwd|secret|api[_-]?key|access[_-]?key|token|credential|private[_-]?key|authorization|dsn)[\"']\s*:\s*[\"'])(.*?)([\"'])"
)
_DEBUG_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_DEBUG_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL | re.IGNORECASE,
)
MAX_AI_DEBUG_CHARS = 8_000


def safe_debug_text(value: object) -> str:
    """Bound and redact untrusted diagnostic text before it reaches stderr."""
    text = str(value).replace("\x00", "�")
    text = _DEBUG_PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", text)
    text = _DEBUG_BEARER.sub("Bearer [REDACTED]", text)
    text = _DEBUG_JSON_SECRET.sub(lambda match: f"{match.group(1)}[REDACTED]{match.group(3)}", text)
    text = _DEBUG_SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    if len(text) > MAX_AI_DEBUG_CHARS:
        text = text[: MAX_AI_DEBUG_CHARS - 16].rstrip() + "\n...[truncated]"
    return text


AI_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "project_purpose": {
            "type": "string",
            "description": "One or two concise sentences explaining the user-facing or engineering purpose.",
            "maxLength": 500,
        },
        "architecture_summary": {
            "type": "string",
            "description": "Two to four concise sentences inferring architecture from selected files and modules.",
            "maxLength": 800,
        },
        "key_components": {
            "type": "array",
            "description": "Components with their concrete responsibilities; never bare filenames.",
            "items": {"type": "string", "maxLength": 400},
            "minItems": 2,
            "maxItems": 12,
        },
        "important_relationships": {
            "type": "array",
            "description": "Concrete data flow, call, dependency, or ownership relationships between components.",
            "items": {"type": "string", "maxLength": 400},
            "minItems": 2,
            "maxItems": 12,
        },
        "coding_agent_notes": {
            "type": "array",
            "description": "Actionable implementation or verification guidance for coding agents.",
            "items": {"type": "string", "maxLength": 400},
            "minItems": 2,
            "maxItems": 12,
        },
    },
    "required": [
        "project_purpose",
        "architecture_summary",
        "key_components",
        "important_relationships",
        "coding_agent_notes",
    ],
}


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        opener: Callable[..., object] = urlopen,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            normalized = "http://" + normalized
        self.base_url = normalized
        self.timeout = timeout
        self._opener = opener
        self._diagnostic = diagnostic

    def _debug(self, message: str) -> None:
        if self._diagnostic is not None:
            self._diagnostic(safe_debug_text(message))

    def generate(self, model: str, prompt: str) -> dict[str, object]:
        payload = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": AI_RESPONSE_SCHEMA,
                "options": {"temperature": 0},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None)
                if status is None and callable(getattr(response, "getcode", None)):
                    status = response.getcode()
                self._debug(f"Ollama HTTP status: {status if status is not None else 'unknown'}")
                body = response.read(MAX_AI_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            self._debug(f"Ollama HTTP status: {exc.code}")
            raise OllamaError("Ollama request failed.") from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            self._debug("Ollama HTTP status: unavailable")
            raise OllamaError("Ollama request failed.") from exc
        if len(body) > MAX_AI_RESPONSE_BYTES:
            raise OllamaError("Ollama response exceeded the safety limit.")
        try:
            raw_envelope = body.decode("utf-8")
        except UnicodeError as exc:
            self._debug(f"JSON parse error: response is not UTF-8 ({type(exc).__name__})")
            raise OllamaJSONError("Ollama returned an invalid response.") from exc
        try:
            envelope = json.loads(raw_envelope)
        except json.JSONDecodeError as exc:
            self._debug(f"Raw model response before parsing: {raw_envelope}")
            self._debug(f"JSON parse error: HTTP response at line {exc.lineno}, column {exc.colno}: {exc.msg}")
            raise OllamaJSONError("Ollama returned invalid JSON.") from exc
        try:
            generated = envelope["response"]
        except (KeyError, TypeError) as exc:
            self._debug(f"Raw model response before parsing: {raw_envelope}")
            self._debug("JSON parse error: Ollama response envelope has no `response` field")
            raise OllamaJSONError("Ollama returned an invalid response envelope.") from exc
        raw_generated = generated if isinstance(generated, str) else json.dumps(generated, ensure_ascii=False)
        self._debug(f"Raw model response before parsing: {raw_generated}")
        try:
            result = json.loads(generated) if isinstance(generated, str) else generated
        except json.JSONDecodeError as exc:
            self._debug(f"JSON parse error: model output at line {exc.lineno}, column {exc.colno}: {exc.msg}")
            raise OllamaJSONError("Ollama model output is invalid JSON.") from exc
        if not isinstance(result, dict):
            self._debug("JSON parse error: model output is not a JSON object")
            raise OllamaJSONError("Ollama returned an invalid enrichment object.")
        return result
