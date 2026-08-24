from __future__ import annotations

from pathlib import Path

from npiac.analyzer import analyze_repository
from npiac.cli import main
from npiac.enrichment import build_ai_prompt
from npiac.renderer import GENERATED_MARKER, render_context
from npiac.scanner import scan_repository


def _write(root: Path, relative: str, content: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_custom_output_is_excluded_from_later_analysis(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "print('production')\n")
    output_name = "SELF_CONTEXT_14B.md"

    assert main([str(tmp_path), "--output", output_name]) == 0
    context = analyze_repository(tmp_path)

    assert output_name not in context.tree_paths
    assert output_name not in context.tree
    assert output_name not in {item.path for item in context.important_files}
    assert output_name not in build_ai_prompt(tmp_path, context)


def test_current_requested_output_is_excluded_before_overwrite(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "print('production')\n")
    output_name = "custom-output.md"
    _write(tmp_path, output_name, "# Existing user Markdown\n")

    assert main([str(tmp_path), "--output", output_name, "--force"]) == 0
    rendered = (tmp_path / output_name).read_text(encoding="utf-8")
    assert output_name not in rendered


def test_multiple_generated_markdown_files_are_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "print('production')\n")
    _write(tmp_path, "README.md", "# Production documentation\n")

    assert main([str(tmp_path), "--output", "SELF_CONTEXT.md"]) == 0
    assert main([str(tmp_path), "--output", "reports/SELF_CONTEXT_14B.md"]) == 0

    snapshot = scan_repository(tmp_path)
    assert snapshot.paths == ("main.py", "README.md")
    rendered = render_context(analyze_repository(tmp_path))
    assert "SELF_CONTEXT.md" not in rendered
    assert "SELF_CONTEXT_14B.md" not in rendered


def test_user_authored_markdown_without_marker_remains_visible(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "print('production')\n")
    _write(tmp_path, "notes.md", "# Deployment notes\nKeep this file in the repository.\n")
    _write(tmp_path, "SELF_CONTEXT.md", GENERATED_MARKER + "\n# Generated context\n")

    context = analyze_repository(tmp_path)
    assert "notes.md" in context.tree_paths
    assert "SELF_CONTEXT.md" not in context.tree_paths
    assert "notes.md" in context.tree


def test_repeated_self_analysis_is_deterministic_with_custom_output(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "print('production')\n")
    output_name = "SELF_CONTEXT.md"

    assert main([str(tmp_path), "--output", output_name]) == 0
    first_output = (tmp_path / output_name).read_text(encoding="utf-8")
    assert main([str(tmp_path), "--output", output_name]) == 0
    assert (tmp_path / output_name).read_text(encoding="utf-8") == first_output

    analyses = {render_context(analyze_repository(tmp_path)) for _ in range(5)}
    assert len(analyses) == 1
    assert output_name not in analyses.pop()
