from pathlib import Path

from npiac.scanner import scan_repository


def test_legacy_repocontextignore_rules_and_negation(tmp_path: Path) -> None:
    (tmp_path / "docs" / "generated").mkdir(parents=True)
    (tmp_path / "docs" / "generated" / "drop.md").write_text("drop", encoding="utf-8")
    (tmp_path / "docs" / "generated" / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "debug.log").write_text("drop", encoding="utf-8")
    (tmp_path / "keep.log").write_text("keep", encoding="utf-8")
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / ".repocontextignore").write_text(
        "# generated content\ndocs/generated/\n!docs/generated/keep.md\n*.log\n!keep.log\n",
        encoding="utf-8",
    )

    paths = scan_repository(tmp_path).paths
    assert ".repocontextignore" in paths
    assert "docs/generated/drop.md" not in paths
    assert "docs/generated/keep.md" in paths
    assert "debug.log" not in paths
    assert "keep.log" in paths
    assert "main.py" in paths


def test_npiacignore_is_primary_and_can_override_legacy_rules(tmp_path: Path) -> None:
    (tmp_path / "keep.log").write_text("keep", encoding="utf-8")
    (tmp_path / "drop.log").write_text("drop", encoding="utf-8")
    (tmp_path / ".repocontextignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / ".npiacignore").write_text("!keep.log\n", encoding="utf-8")

    paths = scan_repository(tmp_path).paths
    assert ".npiacignore" in paths
    assert ".repocontextignore" in paths
    assert "keep.log" in paths
    assert "drop.log" not in paths


def test_ignore_output_is_deterministic(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("", encoding="utf-8")
    (tmp_path / "a.txt").write_text("", encoding="utf-8")
    (tmp_path / ".repocontextignore").write_text("z.txt\n", encoding="utf-8")
    assert scan_repository(tmp_path).paths == scan_repository(tmp_path).paths
