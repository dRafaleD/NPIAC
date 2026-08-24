# Changelog

All notable changes to NPIAC are documented in this file.

## [Unreleased]

### Security

- Confined output writes to safe non-symlink paths inside the selected repository, including when `--force` is used.
- Added root-containment revalidation, fail-closed ignore handling, bounded manifest/scanner resources, and filesystem-fallback `.gitignore` filtering.
- Hardened Ollama redirect/base-URL handling, source-excerpt redaction, debug-log redaction, and untrusted Markdown metadata rendering.

## [0.6.0] - 2026-08-24

First public beta release.

### Highlights

- Deterministic repository analysis produces stable, local-first Markdown without requiring AI or network access.
- Smart file ranking prioritizes manifests, production entry points, framework conventions, business logic, models, data access, and related tests while deprioritizing fixtures, samples, generated files, and build output.
- Context budgeting trims lower-priority content deterministically while preserving manifests, entry points, and other high-value files where the requested size allows.
- `.npiacignore` provides ordered ignore rules with glob patterns, directory rules, comments, and negation; the legacy `.repocontextignore` filename remains temporarily supported.
- Optional Ollama enrichment adds bounded architecture and coding-agent guidance after deterministic analysis, with strict local-first safety limits and graceful fallback.
- Multi-language and workspace detection covers Python, JavaScript/TypeScript, Rust, C#, generic repositories, monorepos, and multi-application entry points.
- Generated-output exclusion prevents current output paths, `CONTEXT*.md`, and Markdown carrying the NPIAC generated marker from reappearing in later analysis or AI input.
- The `repocontext` console command remains available as a deprecated compatibility alias for `npiac`.

### Release notes

- Python 3.11 or newer is required.
- NPIAC has no required runtime dependencies.
- Ollama enrichment remains opt-in; deterministic mode is the default and source of truth.
- This release does not include hosted AI providers, embeddings, remote repository fetching, AST analysis, or a GUI/TUI.

### Documentation

- Added release notes, contribution guidance, security reporting guidance, a quick-start guide, and an architecture overview.
