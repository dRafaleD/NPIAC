from pathlib import Path

from npiac.cli import build_parser, deprecated_main, main
from npiac.renderer import GENERATED_MARKER


def test_cli_generates_and_refreshes_default_output(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    output = tmp_path / "CONTEXT.md"
    first = output.read_text(encoding="utf-8")
    assert GENERATED_MARKER in first
    assert main([str(tmp_path)]) == 0
    assert output.read_text(encoding="utf-8") == first


def test_cli_protects_existing_user_file(tmp_path: Path) -> None:
    output = tmp_path / "notes.md"
    output.write_text("user content", encoding="utf-8")
    assert main([str(tmp_path), "--output", "notes.md"]) == 3
    assert output.read_text(encoding="utf-8") == "user content"
    assert main([str(tmp_path), "--output", "notes.md", "--force"]) == 0
    assert GENERATED_MARKER in output.read_text(encoding="utf-8")


def test_cli_reports_invalid_path(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing")]) == 2


def test_cli_stdout_does_not_write_file(tmp_path: Path, capsys) -> None:
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    assert main([str(tmp_path), "--stdout"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(GENERATED_MARKER)
    assert not (tmp_path / "CONTEXT.md").exists()


def test_cli_budget_limits_written_output(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    for index in range(30):
        (tmp_path / f"file_{index:02}.py").write_text("", encoding="utf-8")
    assert main([str(tmp_path), "--budget", "300"]) == 0
    output = (tmp_path / "CONTEXT.md").read_text(encoding="utf-8")
    assert len(output) <= 300
    assert "trim" in output.casefold()


def test_cli_uses_npiac_brand_and_deprecated_alias_warns(tmp_path: Path, capsys) -> None:
    assert build_parser().prog == "npiac"
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    assert deprecated_main([str(tmp_path), "--stdout"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(GENERATED_MARKER)
    assert "deprecated command" in captured.err
    assert "use `npiac`" in captured.err
