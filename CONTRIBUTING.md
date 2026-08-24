# Contributing to NPIAC

Thanks for helping improve NPIAC. Contributions should preserve deterministic, local-first behavior and remain focused on practical repository context generation.

## Local setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on POSIX systems or `.venv\Scripts\Activate.ps1` in Windows PowerShell, then install the project and development tools:

```bash
python -m pip install -e .
python -m pip install pytest build twine
```

## Tests and release checks

Run the complete suite and compilation check:

```bash
python -m pytest
python -m compileall -q src tests
```

When changing rendering or detection, update the matching fixture and golden Markdown only when the intended deterministic output changes. Before release-related pull requests, also run:

```bash
python -m build
python -m twine check dist/*
```

## Coding expectations

- Prefer the Python standard library and small, testable functions.
- Keep ordering deterministic across platforms and repeated runs.
- Preserve safety exclusions and the no-network default.
- Do not let optional AI override deterministic findings.
- Add regression tests for behavior changes and failure paths.
- Avoid unrelated refactors, hidden state, and machine-specific assumptions.

## Pull-request workflow

1. Start from the latest project state and create a focused branch.
2. Make one coherent change with tests and concise documentation.
3. Run the full suite locally on a supported Python version.
4. Describe the problem, approach, compatibility impact, and verification in the pull request.
5. Address review feedback without broadening the change unnecessarily.

Do not include secrets, generated `CONTEXT*.md`, virtual environments, caches, build directories, or local machine paths in a contribution.
