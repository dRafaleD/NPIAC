from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from .analyzer import analyze_repository
from .constants import GENERATED_MARKER
from .enrichment import enrich_context
from .ollama import OllamaClient
from .renderer import render_context


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("budget must be a positive integer")
    return parsed


def _nonempty(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("value must not be empty")
    return value.strip()


def build_parser(prog: str = "npiac") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Generate deterministic repository context for coding agents.",
    )
    parser.add_argument("path", nargs="?", default=".", help="Repository path (default: current directory)")
    parser.add_argument("--output", default="CONTEXT.md", help="Output file, relative to the repository root")
    parser.add_argument("--stdout", action="store_true", help="Print Markdown instead of writing a file")
    parser.add_argument("--force", action="store_true", help="Overwrite a non-NPIAC output file")
    parser.add_argument("--budget", type=_positive_integer, help="Maximum number of characters in the generated context")
    parser.add_argument("--ai", action="store_true", help="Add optional local AI enrichment after deterministic analysis")
    parser.add_argument("--debug-ai", action="store_true", help="Write redacted Ollama diagnostics to stderr")
    parser.add_argument("--provider", choices=("ollama",), default="ollama", help="AI provider (default: ollama)")
    parser.add_argument(
        "--model",
        type=_nonempty,
        default=os.environ.get("NPIAC_OLLAMA_MODEL", os.environ.get("REPOCONTEXT_OLLAMA_MODEL", "llama3.2")),
        help="Ollama model (default: llama3.2)",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=os.environ.get(
            "NPIAC_OLLAMA_BASE_URL",
            os.environ.get("REPOCONTEXT_OLLAMA_BASE_URL", "http://localhost:11434"),
        ),
        help="Ollama base URL (default: http://localhost:11434)",
    )
    return parser


def _write_atomic(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        try:
            existing = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise FileExistsError(f"Cannot safely inspect existing output: {path}") from exc
        if GENERATED_MARKER not in existing:
            raise FileExistsError(f"Refusing to overwrite existing file without --force: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            handle.write(content)
            temporary_name = handle.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def _run(argv: list[str] | None, command_name: str) -> int:
    args = build_parser(command_name).parse_args(argv)
    try:
        root = Path(args.path).expanduser().resolve()
        output = Path(args.output).expanduser()
        if not output.is_absolute():
            output = root / output
        output = output.resolve()
        excluded: set[str] = set()
        try:
            excluded.add(output.relative_to(root).as_posix())
        except ValueError:
            pass
        context = analyze_repository(root, excluded)
        if args.ai and args.provider == "ollama":
            diagnostic = (
                (lambda message: print(f"{command_name} AI debug: {message}", file=sys.stderr))
                if args.debug_ai
                else None
            )
            client = (
                OllamaClient(args.ollama_base_url, diagnostic=diagnostic)
                if diagnostic is not None
                else OllamaClient(args.ollama_base_url)
            )
            context = enrich_context(root, context, client, args.model, diagnostic=diagnostic)
        rendered = render_context(context, args.budget)
        if args.stdout:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(rendered)
        else:
            _write_atomic(output, rendered, args.force)
            print(f"Generated {output}")
        return 0
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"{command_name}: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"{command_name}: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"{command_name}: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    return _run(argv, "npiac")


def deprecated_main(argv: list[str] | None = None) -> int:
    print("repocontext: deprecated command; use `npiac` instead.", file=sys.stderr)
    return _run(argv, "repocontext")
