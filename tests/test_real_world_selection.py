from __future__ import annotations

from pathlib import Path

from npiac.analyzer import analyze_repository
from npiac.renderer import render_context
from npiac.scanner import scan_repository


def _write(root: Path, relative: str, content: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_fixture_dotnet_program_is_not_a_repository_entry_point(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "production-python"\nversion = "0.1.0"\ndependencies = ["fastapi"]\n'
        '[project.scripts]\nproduction = "production.main:main"\n',
    )
    _write(tmp_path, "src/production/main.py", "def main():\n    return 0\n")
    _write(
        tmp_path,
        "tests/fixtures/dotnet/Sample.csproj",
        '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>',
    )
    _write(tmp_path, "tests/fixtures/dotnet/Program.cs", 'Console.WriteLine("fixture");')

    context = analyze_repository(tmp_path)
    assert context.project_name == "production-python"
    assert context.languages == ("Python",)
    assert "ASP.NET Core" not in context.frameworks
    assert all("tests/fixtures" not in path for _, path in context.entry_points)
    assert ("CLI `production`", "src/production/main.py") in context.entry_points


def test_example_app_does_not_override_real_project_metadata(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "package.json",
        '{"name":"production-app","dependencies":{"express":"latest"}}',
    )
    _write(tmp_path, "src/index.ts", "export const production = true;")
    _write(
        tmp_path,
        "examples/demo-app/package.json",
        '{"name":"sample-app","dependencies":{"next":"latest","react":"latest"}}',
    )
    _write(tmp_path, "examples/demo-app/src/index.ts", "export const sample = true;")

    context = analyze_repository(tmp_path)
    assert context.project_name == "production-app"
    assert "Express" in context.frameworks
    assert "Next.js" not in context.frameworks
    assert "React" not in context.frameworks
    assert all("examples/" not in path for _, path in context.entry_points)
    assert all("examples/" not in item.path for item in context.important_files)


def test_generated_context_files_do_not_reappear_in_scan_or_tree(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "print('production')\n")
    _write(tmp_path, "CONTEXT.md", "old context")
    _write(tmp_path, "CONTEXT-small.md", "small context")
    _write(tmp_path, "docs/CONTEXT.generated.md", "nested context")

    snapshot = scan_repository(tmp_path)
    assert snapshot.paths == ("main.py",)
    rendered = render_context(analyze_repository(tmp_path))
    assert "CONTEXT.md" not in rendered
    assert "CONTEXT-small.md" not in rendered
    assert "CONTEXT.generated.md" not in rendered


def test_real_monorepo_subprojects_remain_detectable(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/web/package.json",
        '{"name":"workspace-web","dependencies":{"express":"latest"}}',
    )
    _write(tmp_path, "packages/web/src/index.ts", "export const web = true;")
    _write(
        tmp_path,
        "crates/worker/Cargo.toml",
        '[package]\nname = "workspace-worker"\nversion = "0.1.0"\n[dependencies]\ntokio = "1"\n',
    )
    _write(tmp_path, "crates/worker/src/main.rs", "fn main() {}\n")
    _write(
        tmp_path,
        "services/Web/Web.csproj",
        '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>',
    )
    _write(tmp_path, "services/Web/Program.cs", 'Console.WriteLine("web");')

    context = analyze_repository(tmp_path)
    assert set(context.languages) == {"C#", "JavaScript", "Rust", "TypeScript"}
    assert {"ASP.NET Core", "Express", "Tokio"} <= set(context.frameworks)
    entry_paths = {path for _, path in context.entry_points}
    assert "packages/web/src/index.ts" in entry_paths
    assert "crates/worker/src/main.rs" in entry_paths
    assert "services/Web/Program.cs" in entry_paths
    important_paths = {item.path for item in context.important_files}
    assert "packages/web/package.json" in important_paths
    assert "crates/worker/Cargo.toml" in important_paths
    assert "services/Web/Web.csproj" in important_paths


def test_golden_and_snapshot_artifacts_are_not_important_files(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name":"production"}')
    _write(tmp_path, "src/index.ts", "export const value = 1;")
    _write(tmp_path, "tests/golden/package.json", '{"name":"golden-copy"}')
    _write(tmp_path, "tests/golden/index.ts", "export const golden = true;")
    _write(tmp_path, "tests/__snapshots__/index.snapshot", "snapshot")

    context = analyze_repository(tmp_path)
    assert all("tests/golden/" not in item.path for item in context.important_files)
    assert all("__snapshots__" not in item.path for item in context.important_files)


def test_real_world_selection_output_is_deterministic(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name":"stable","dependencies":{"express":"latest"}}')
    _write(tmp_path, "src/index.ts", "export const value = 1;")
    _write(tmp_path, "examples/app/package.json", '{"name":"ignored-example"}')
    _write(tmp_path, "examples/app/src/index.ts", "export const ignored = true;")
    outputs = {render_context(analyze_repository(tmp_path)) for _ in range(5)}
    assert len(outputs) == 1


def test_react_rust_tauri_repo_reports_all_production_apps_and_cleans_tree(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "package.json",
        '{"name":"desktop-suite","dependencies":{"react":"latest"},"devDependencies":{"vite":"latest"}}',
    )
    _write(tmp_path, "src/main.tsx", "export const App = () => null;")
    _write(tmp_path, "src/assets/logo.svg", "<svg></svg>")
    _write(
        tmp_path,
        "server/Cargo.toml",
        '[package]\nname = "server"\nversion = "0.1.0"\n[dependencies]\ntokio = "1"\n',
    )
    _write(tmp_path, "server/src/main.rs", "fn main() {}\n")
    _write(
        tmp_path,
        "src-tauri/Cargo.toml",
        '[package]\nname = "desktop"\nversion = "0.1.0"\n',
    )
    _write(tmp_path, "src-tauri/src/main.rs", "fn main() {}\n")

    _write(tmp_path, "tests/fixtures/rust/src/main.rs", "fn main() {}\n")
    _write(tmp_path, "examples/web/src/main.tsx", "export const Demo = () => null;")
    _write(tmp_path, ".vs/cache/state.bin", "noise")
    _write(tmp_path, ".idea/workspace.xml", "noise")
    _write(tmp_path, "release/desktop.exe", "noise")
    _write(tmp_path, "releases/installer.msi", "noise")
    _write(tmp_path, "out/archive.zip", "noise")
    _write(tmp_path, "generated-schemas/client/schema.json", "noise")
    for index in range(10):
        _write(tmp_path, f"assets/icons/icon-{index:02}.png", "image")
    _write(tmp_path, "docs/architecture.png", "diagram")
    _write(tmp_path, "docs/releases/v1.md", "release notes")

    context = analyze_repository(tmp_path)
    assert ("Frontend", "src/main.tsx") in context.entry_points
    assert ("Rust server", "server/src/main.rs") in context.entry_points
    assert ("Tauri desktop", "src-tauri/src/main.rs") in context.entry_points
    assert all("fixtures/" not in path and "examples/" not in path for _, path in context.entry_points)

    assert "docs/architecture.png" in context.tree_paths
    assert "docs/releases/v1.md" in context.tree_paths
    assert "src/assets/logo.svg" in context.tree_paths
    assert not any(path.startswith("assets/icons/") for path in context.tree_paths)
    assert not any(
        path.startswith((".idea/", ".vs/", "release/", "releases/", "out/", "generated-schemas/"))
        for path in context.tree_paths
    )
    assert not any(path.endswith((".exe", ".msi", ".zip")) for path in context.tree_paths)

    outputs = {render_context(analyze_repository(tmp_path)) for _ in range(5)}
    assert len(outputs) == 1
