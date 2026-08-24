import shutil
from pathlib import Path

import pytest

from npiac.analyzer import analyze_repository
from npiac.renderer import render_context


FIXTURES = Path(__file__).parent / "fixtures"
GOLDENS = Path(__file__).parent / "golden"
PROJECTS = (
    "python_project",
    "node_project",
    "rust_project",
    "dotnet_project",
    "generic_repo",
    "malformed_manifest",
    "empty_repo",
)


@pytest.mark.parametrize("project", PROJECTS)
def test_fixture_matches_golden(project: str) -> None:
    rendered = render_context(analyze_repository(FIXTURES / project))
    expected = (GOLDENS / f"{project}.md").read_text(encoding="utf-8")
    assert rendered == expected
    assert render_context(analyze_repository(FIXTURES / project)) == rendered


def test_sensitive_content_is_not_scanned_or_rendered(tmp_path: Path) -> None:
    project = tmp_path / "python_project"
    shutil.copytree(FIXTURES / "python_project", project)
    (project / ".env").write_text("SECRET=must-not-appear\n", encoding="utf-8")
    rendered = render_context(analyze_repository(project))
    assert ".env" not in rendered
    assert "must-not-appear" not in rendered
