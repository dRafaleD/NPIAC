from pathlib import Path

from npiac.analyzer import analyze_repository


FIXTURES = Path(__file__).parent / "fixtures"


def test_python_detection() -> None:
    context = analyze_repository(FIXTURES / "python_project")
    assert context.project_name == "sample-api"
    assert context.languages == ("Python",)
    assert "FastAPI" in context.frameworks
    assert "pytest" in context.test_frameworks
    assert ("CLI `sample-api`", "src/sample/main.py") in context.entry_points


def test_node_detection() -> None:
    context = analyze_repository(FIXTURES / "node_project")
    assert context.project_name == "sample-web"
    assert context.languages == ("JavaScript", "TypeScript")
    assert set(context.frameworks) == {"Express", "Next.js", "React", "Vite"}
    assert context.package_managers == ("npm",)
    assert context.databases == ("PostgreSQL",)


def test_rust_detection() -> None:
    context = analyze_repository(FIXTURES / "rust_project")
    assert set(context.frameworks) == {"Axum", "Tokio"}
    assert context.package_managers == ("Cargo",)


def test_dotnet_detection() -> None:
    context = analyze_repository(FIXTURES / "dotnet_project")
    assert set(context.frameworks) == {"ASP.NET Core", "Entity Framework Core"}
    assert context.test_frameworks == ("xUnit",)


def test_malformed_manifests_do_not_stop_analysis() -> None:
    context = analyze_repository(FIXTURES / "malformed_manifest")
    assert len(context.warnings) == 4
    assert "Python" in context.languages


def test_requirements_txt_is_parsed(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("Flask==3.0\npsycopg>=3\n", encoding="utf-8")
    context = analyze_repository(tmp_path)
    assert "Flask" in context.frameworks
    assert "PostgreSQL" in context.databases
