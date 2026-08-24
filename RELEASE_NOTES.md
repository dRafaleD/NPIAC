# NPIAC 0.6.0 Release Notes

NPIAC 0.6.0 is the first public beta of **Not Prompt, It’s Also Context**.

## What is included

- Deterministic local repository analysis with stable Markdown output and no required AI or network access.
- Smart importance ranking for manifests, production entry points, framework conventions, business logic, models, data access, configuration, and related tests.
- Deterministic context budgeting that trims lower-priority content before protected high-value files.
- Ordered `.npiacignore` rules with glob patterns, directory rules, comments, and negation.
- Optional local Ollama enrichment for purpose, architecture, component, relationship, and coding-agent guidance.
- Python, JavaScript/TypeScript, Rust, C#, generic repository, monorepo, and multi-application detection.
- Generated-output exclusion for the active output path, `CONTEXT*.md`, and Markdown containing the NPIAC generated marker.
- A deprecated `repocontext` command alias and legacy ignore/environment-variable compatibility for migration.

## Safety and fallback behavior

Deterministic findings remain the source of truth. Ollama enrichment is bounded, uses selected safe source excerpts, and falls back to deterministic output with a warning if enrichment fails. Secret-like files, credentials, private keys, lockfile contents, ignored paths, binaries, and unsafe symlinks are excluded from AI input.

## Compatibility

- Python 3.11–3.14
- Windows, macOS, and Linux through standard-library cross-platform behavior
- No required runtime dependencies

## Current beta boundaries

This release does not include hosted AI providers, embeddings, remote repository fetching, Git-history analysis, AST analysis, plugins, watch mode, or a GUI/TUI.
