# NPIAC Quick Start

NPIAC creates deterministic repository context for coding agents and works without AI.

## Install

Python 3.11 or newer is required.

```bash
git clone https://github.com/dRafaleD/NPIAC.git
cd NPIAC
python -m pip install .
```

After the public PyPI release, install with `python -m pip install npiac`.

## Generate context

From a repository root:

```bash
npiac .
```

The default output is `CONTEXT.md`. Existing NPIAC-generated output can be refreshed safely; overwriting another file requires `--force`.

Output paths must resolve inside the selected repository. NPIAC rejects parent traversal, outside absolute paths, symlink/junction components, version-control metadata, and known sensitive filenames. `--force` does not bypass these boundaries.

```bash
npiac . --stdout
npiac . --output docs/PROJECT_CONTEXT.md
npiac . --output PROJECT_CONTEXT.md --force
```

## Limit output size

`--budget` is a maximum character count:

```bash
npiac . --budget 5000
```

NPIAC trims lower-priority sections first and includes a warning when content is reduced.

## Ignore repository-specific paths

Create `.npiacignore`:

```gitignore
docs/generated/
*.snapshot
!important.snapshot
```

Rules are ordered. Later matches override earlier ones. The deprecated `.repocontextignore` filename is still accepted and is evaluated before `.npiacignore`.

Sensitive-file exclusions cannot be negated. If an ignore file is unreadable, invalid, oversized, or a symlink, NPIAC stops instead of scanning without its privacy rules.

## Add local Ollama enrichment

Install and start Ollama separately, then ensure the requested model exists locally:

```bash
npiac . --ai --model llama3.2
```

Use another local endpoint when needed:

```bash
npiac . --ai --model qwen3 --ollama-base-url http://localhost:11434
```

If Ollama cannot be reached or rejects the response, NPIAC still writes deterministic context and adds a warning. Use `--debug-ai` for redacted diagnostics on standard error.

## Legacy command

`repocontext .` remains available temporarily and prints a deprecation warning. Prefer `npiac` in new scripts and documentation.
