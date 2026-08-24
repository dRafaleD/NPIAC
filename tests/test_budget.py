from pathlib import Path

import pytest

from npiac.analyzer import analyze_repository
from npiac.renderer import TRIM_WARNING, render_context


FIXTURES = Path(__file__).parent / "fixtures"


def test_budget_trims_output_and_adds_warning() -> None:
    context = analyze_repository(FIXTURES / "python_project")
    full = render_context(context)
    trimmed = render_context(context, budget=700)
    assert len(full) > 700
    assert len(trimmed) <= 700
    assert TRIM_WARNING in trimmed


def test_priority_preserves_manifest_and_entry_point() -> None:
    context = analyze_repository(FIXTURES / "python_project")
    trimmed = render_context(context, budget=700)
    assert "`pyproject.toml` — Python project manifest" in trimmed
    assert "`src/sample/main.py` — Probable entry point" in trimmed
    assert "tests/test_main.py" not in trimmed


def test_budgeted_output_is_deterministic() -> None:
    context = analyze_repository(FIXTURES / "node_project")
    outputs = {render_context(context, budget=600) for _ in range(5)}
    assert len(outputs) == 1


@pytest.mark.parametrize("budget", (1, 5, 20, 60, 100))
def test_very_small_budgets_are_respected(budget: int) -> None:
    context = analyze_repository(FIXTURES / "python_project")
    output = render_context(context, budget=budget)
    assert 0 < len(output) <= budget
    assert "trim" in output.casefold() or output == "!"


def test_no_budget_keeps_existing_output_unchanged() -> None:
    context = analyze_repository(FIXTURES / "python_project")
    expected = (Path(__file__).parent / "golden" / "python_project.md").read_text(encoding="utf-8")
    assert render_context(context) == expected
