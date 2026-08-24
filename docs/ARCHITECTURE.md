# NPIAC Architecture

NPIAC uses a small staged pipeline:

```text
scan → detect → select → model → optional AI enrichment → render
```

Deterministic analysis is always the source of truth. Optional AI can add explanatory sections but cannot replace detected languages, frameworks, manifests, entry points, or important-file rankings.

## 1. Scan

`scanner.py` discovers repository files with `git ls-files --cached --others --exclude-standard` when possible and falls back to a filesystem walk. It applies default directory and binary exclusions, `.npiacignore`, legacy ignore rules, sensitive-file checks, symlink safety, and generated-output exclusion. The result is an ordered `RepositorySnapshot`.

## 2. Detect

Detectors under `detectors/` inspect filenames and parse supported manifests using the standard library. Each detector contributes evidence to a shared `DetectionResult`; a malformed manifest or failed detector records a warning without preventing generic output.

Supported detector families are Python, JavaScript/TypeScript, Rust, .NET/C#, and generic repository signals.

## 3. Select

`selectors.py` identifies production entry points, tests, configuration, important files, and tree paths. Importance ranking uses deterministic path, filename, framework-convention, manifest-proximity, and production-versus-fixture heuristics. Stable score and path ordering resolves ties.

## 4. Model

`models.py` defines the immutable file snapshot, important-file records, repository context, and optional enrichment data. `analyzer.py` coordinates scanning, detection, selection, and model construction.

## 5. Optional AI enrichment

When `--ai` is enabled, `enrichment.py` builds a bounded prompt from deterministic technologies, the tree, selected important files and reasons, and safe source excerpts. `ollama.py` calls the configured Ollama endpoint and validates structured output. Weak list items are filtered; invalid or unavailable enrichment falls back to deterministic output with a warning.

AI enrichment never mutates deterministic findings.

## 6. Render

`renderer.py` converts `RepositoryContext` into stable Markdown. Budgeted rendering removes lower-priority content in deterministic stages and preserves high-value facts where possible. `cli.py` excludes the requested output from analysis and writes the final file atomically.

## Determinism and safety boundaries

- Sorting is explicit and case-stable.
- Network access occurs only when `--ai` is requested.
- Secret-like files, credentials, private keys, lockfiles, ignored paths, binary files, generated output, and unsafe symlinks are excluded from AI input.
- Per-file excerpts, total prompt size, tree text, selected-file text, and response size are bounded.
- Generated Markdown carries a marker so later scans can exclude it regardless of custom filename.
