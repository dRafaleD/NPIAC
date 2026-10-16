import shutil
import subprocess
from pathlib import Path

import pytest
from npiac.scanner import scan_repository


@pytest.mark.skipif(shutil.which("git") is None, reason="Git required")
def test_analysis_never_executes_repository_fsmonitor(tmp_path: Path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "-q")
    (tmp_path / "visible.txt").write_text("ordinary input")
    git("add", "visible.txt")
    marker = tmp_path / "unexpected-hook"
    hook = tmp_path / ".git" / "monitor"
    hook.write_text('#!/bin/sh\nprintf called > "' + marker.as_posix() + '"\n')
    hook.chmod(0o755)
    git("config", "core.fsmonitor", '"' + hook.as_posix() + '"')
    snapshot = scan_repository(tmp_path)
    assert snapshot.is_git
    assert "visible.txt" in snapshot.paths
    assert not marker.exists()
