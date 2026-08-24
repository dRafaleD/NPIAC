from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from npiac.scanner import scan_repository


def test_filesystem_scan_skips_generated_dirs_and_symlink_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.js").write_text("", encoding="utf-8")
    (tmp_path / ".env.local").write_text("SECRET=yes", encoding="utf-8")
    snapshot = scan_repository(tmp_path)
    assert snapshot.paths == ("src/main.py",)


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")
def test_git_scan_respects_gitignore(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("visible", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    snapshot = scan_repository(tmp_path)
    assert snapshot.is_git
    assert ".gitignore" in snapshot.paths
    assert "visible.txt" in snapshot.paths
    assert "ignored.txt" not in snapshot.paths
