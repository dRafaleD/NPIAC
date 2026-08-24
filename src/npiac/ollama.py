from __future__ import annotations

import json
import socket
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .constants import MAX_AI_RESPONSE_BYTES
from .safety import redact_sensitive_text


class OllamaError(RuntimeError):
    """A stable, user-safe Ollama failure."""


class OllamaJSONError(OllamaError):
    """Ollama returned content that could not be parsed as JSON."""


class OllamaSchemaError(OllamaError):
    """Ollama returned JSON that does not match the enrichment schema."""


class OllamaQualityError(OllamaError):
    """Ollama returned structurally valid but low-quality enrichment."""


Diagnostic = Callable[[str], None]

MAX_AI_DEBUG_CHARS = 8_000


def safe_debug_text(value: object) -> str:
    """Bound and redact untrusted diagnostic text before it reaches stderr."""
    text = redact_sensitive_text(str(value).replace("\x00", "�"))
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


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = build_opener(_NoRedirectHandler()).open


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized or any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise OllamaError("Ollama base URL is invalid.")
    if "://" in normalized and not normalized.startswith(("http://", "https://")):
        raise OllamaError("Ollama base URL must use HTTP or HTTPS.")
    if not normalized.startswith(("http://", "https://")):
        normalized = "http://" + normalized
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise OllamaError("Ollama base URL is invalid.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OllamaError("Ollama base URL must use HTTP or HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise OllamaError("Ollama base URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise OllamaError("Ollama base URL must not contain a query or fragment.")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
        opener: Callable[..., object] = _NO_REDIRECT_OPENER,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._opener = opener
        self._diagnostic = diagnostic

    def _debug(self, message: str) -> None:
        if self._diagnostic is not None:
            self._diagnostic(safe_debug_text(message))

    def generate(self, model: str, prompt: str) -> dict[str, object]:
        base_url = _normalize_base_url(self.base_url)
        if not 0 < self.timeout <= 300:
            raise OllamaError("Ollama timeout is outside the safe range.")
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
            f"{base_url}/api/generate",
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
                if status is not None:
                    try:
                        successful = 200 <= int(status) < 300
                    except (TypeError, ValueError) as exc:
                        raise OllamaError("Ollama returned an invalid HTTP status.") from exc
                    if not successful:
                        raise OllamaError("Ollama returned an unexpected HTTP status.")
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
