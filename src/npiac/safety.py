from __future__ import annotations

import os
import re
import stat
import unicodedata
from html import escape
from pathlib import Path, PurePosixPath, PureWindowsPath

from .constants import MAX_PATH_CHARS, SENSITIVE_NAMES, SENSITIVE_SUFFIXES


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.DOTALL | re.IGNORECASE,
)
_AUTH_HEADER = re.compile(
    r"(?im)^(\s*(?:authorization|proxy-authorization|x-api-key|api-key|cookie|set-cookie)\s*:\s*).*$"
)
_SECRET_KEY_PATTERN = (
    r"password|passwd|secret|client[_-]?secret|api[_-]?key|access[_-]?key|token|credential|"
    r"private[_-]?key|authorization|connection[_-]?string|database[_-]?url|dsn|cookie|session"
)
_JSON_SECRET_DOUBLE = re.compile(
    rf'''(?ix)([\"](?:{_SECRET_KEY_PATTERN})[\"]\s*:\s*[\"])((?:\\.|[^\"\\])*)([\"])'''
)
_JSON_SECRET_SINGLE = re.compile(
    rf"(?ix)(['](?:{_SECRET_KEY_PATTERN})[']\s*:\s*['])((?:\\.|[^'\\])*)(['])"
)
_ASSIGNED_QUOTED_DOUBLE = re.compile(
    rf'''(?ix)(\b(?:{_SECRET_KEY_PATTERN})\b\s*(?:is|=|:)\s*[\"])((?:\\.|[^\"\\])*)([\"])'''
)
_ASSIGNED_QUOTED_SINGLE = re.compile(
    rf"(?ix)(\b(?:{_SECRET_KEY_PATTERN})\b\s*(?:is|=|:)\s*['])((?:\\.|[^'\\])*)(['])"
)
_ASSIGNED_SECRET = re.compile(
    rf'''(?ix)
    \b({_SECRET_KEY_PATTERN})\b
    (\s*(?:is|=|:)\s*[\\"']?)
    ([^\\"',;\s}}]+)
    '''
)
_SECRET_LINE = re.compile(
    r"(?im)^(\s*(?:password|passwd|secret|client[_-]?secret|api[_-]?key|access[_-]?key|token|credential|"
    r"private[_-]?key|authorization|connection[_-]?string|database[_-]?url|dsn|cookie|session)\s*(?:=|:)\s*).*$"
)
_URI_CREDENTIALS = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)([^/@\s:]+):([^/@\s]+)@")
_BEARER_OR_BASIC = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]+")
_KNOWN_TOKEN = re.compile(
    r"(?x)(?:"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b|"
    r"\bgh[opusr]_[A-Za-z0-9]{20,}\b|"
    r"\bsk-[A-Za-z0-9_-]{16,}\b|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    r")"
)


def _has_unsafe_control(value: str) -> bool:
    return bool(_CONTROL_CHARACTERS.search(value)) or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value
    )


def _replace_unsafe_controls(value: str, replacement: str) -> str:
    return "".join(
        replacement if unicodedata.category(character) in {"Cc", "Cf", "Cs"} else character
        for character in value
    )


def sanitize_source_text(value: str) -> str:
    return "".join(
        character
        if character in {"\n", "\r", "\t"} or unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
        else "�"
        for character in value
    )


def is_sensitive_path(path: str) -> bool:
    name = PurePosixPath(path.replace("\\", "/")).name.casefold()
    return (
        name in SENSITIVE_NAMES
        or name.startswith(
            (
                ".env.",
                ".env-",
                "credentials.",
                "credentials_",
                "credentials-",
                "secret.",
                "secrets.",
                "secrets_",
                "secrets-",
                "id_rsa.",
                "id_ed25519.",
                "id_dsa.",
                "id_ecdsa.",
            )
        )
        or name.endswith(SENSITIVE_SUFFIXES)
    )


def normalize_repository_path(value: str) -> str | None:
    raw = value.replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw or len(raw) > MAX_PATH_CHARS or _has_unsafe_control(raw):
        return None
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        return None
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return "/".join(parts)


def is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def resolve_repository_file(root: Path, relative: str) -> Path | None:
    normalized = normalize_repository_path(relative)
    if normalized is None:
        return None
    resolved_root = root.resolve()
    candidate = resolved_root
    try:
        for part in normalized.split("/"):
            candidate /= part
            if is_link(candidate):
                return None
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        return None
    return resolved


def redact_sensitive_text(value: str) -> str:
    text = _PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", value)
    text = _URI_CREDENTIALS.sub(lambda match: f"{match.group(1)}[REDACTED]@", text)
    text = _BEARER_OR_BASIC.sub(lambda match: f"{match.group(1)} [REDACTED]", text)
    text = _JSON_SECRET_DOUBLE.sub(lambda match: f"{match.group(1)}[REDACTED]{match.group(3)}", text)
    text = _JSON_SECRET_SINGLE.sub(lambda match: f"{match.group(1)}[REDACTED]{match.group(3)}", text)
    text = _ASSIGNED_QUOTED_DOUBLE.sub(lambda match: f"{match.group(1)}[REDACTED]{match.group(3)}", text)
    text = _ASSIGNED_QUOTED_SINGLE.sub(lambda match: f"{match.group(1)}[REDACTED]{match.group(3)}", text)
    text = _ASSIGNED_SECRET.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _SECRET_LINE.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    text = _AUTH_HEADER.sub(lambda match: f"{match.group(1)}[REDACTED]", text)
    return _KNOWN_TOKEN.sub("[REDACTED TOKEN]", text)


def contains_sensitive_material(value: str) -> bool:
    return redact_sensitive_text(value) != value


def safe_markdown_inline(value: object, limit: int | None = None) -> str:
    text = _replace_unsafe_controls(str(value), " ")
    text = " ".join(text.split())
    text = redact_sensitive_text(text)
    text = escape(text, quote=False).replace("![", r"\![")
    if limit is not None:
        text = text[:limit].rstrip()
    return text


def markdown_code(value: object) -> str:
    text = _replace_unsafe_controls(str(value), "�")
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    return f"{fence}{text}{fence}"


def lexical_path_within(root: Path, candidate: Path) -> bool:
    try:
        root_value = os.path.normcase(os.path.abspath(root))
        candidate_value = os.path.normcase(os.path.abspath(candidate))
        return os.path.commonpath((root_value, candidate_value)) == root_value
    except (OSError, ValueError):
        return False
