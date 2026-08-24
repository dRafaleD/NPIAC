from __future__ import annotations

from pathlib import Path

from npiac.analyzer import analyze_repository


def _write(root: Path, relative: str, content: str = "") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ranked_paths(root: Path) -> tuple[tuple[str, ...], dict[str, object]]:
    context = analyze_repository(root)
    return tuple(item.path for item in context.important_files), {
        item.path: item for item in context.important_files
    }


def _assert_before(paths: tuple[str, ...], high_value: str, low_value: str) -> None:
    assert high_value in paths
    assert low_value in paths
    assert paths.index(high_value) < paths.index(low_value)


def test_python_high_value_files_rank_above_deep_utilities(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "rank-python"\nversion = "0.1.0"\n')
    _write(tmp_path, "src/app/main.py")
    _write(tmp_path, "src/app/routes/users.py")
    _write(tmp_path, "src/app/services/user_service.py")
    _write(tmp_path, "src/app/models/user.py")
    _write(tmp_path, "src/app/repositories/user_repository.py")
    _write(tmp_path, "tests/test_user_service.py")
    low = "src/utils/internal/deep/common/shared/service_helper.py"
    _write(tmp_path, low)

    paths, files = _ranked_paths(tmp_path)
    for high in (
        "src/app/main.py",
        "src/app/routes/users.py",
        "src/app/services/user_service.py",
        "src/app/models/user.py",
        "src/app/repositories/user_repository.py",
        "tests/test_user_service.py",
    ):
        _assert_before(paths, high, low)
    assert "Test related to an important source file" in files["tests/test_user_service.py"].reasons
    assert "Near a project manifest or configuration root" in files["src/app/services/user_service.py"].reasons
    assert "Deeply nested low-signal utility penalty" in files[low].reasons


def test_node_high_value_files_rank_above_deep_utilities(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name":"rank-node"}')
    _write(tmp_path, "src/index.ts")
    _write(tmp_path, "src/routes/users.ts")
    _write(tmp_path, "src/services/user_service.ts")
    _write(tmp_path, "src/models/user.ts")
    _write(tmp_path, "src/repositories/user_repository.ts")
    _write(tmp_path, "tests/user_service.test.ts")
    low = "src/utils/internal/deep/common/shared/service_helper.ts"
    _write(tmp_path, low)

    paths, _ = _ranked_paths(tmp_path)
    for high in ("src/index.ts", "src/routes/users.ts", "src/services/user_service.ts", "tests/user_service.test.ts"):
        _assert_before(paths, high, low)


def test_rust_high_value_files_rank_above_deep_utilities(tmp_path: Path) -> None:
    _write(tmp_path, "Cargo.toml", '[package]\nname = "rank-rust"\nversion = "0.1.0"\n')
    _write(tmp_path, "src/main.rs")
    _write(tmp_path, "src/routes/users.rs")
    _write(tmp_path, "src/services/user_service.rs")
    _write(tmp_path, "src/models/user.rs")
    _write(tmp_path, "src/repositories/user_repository.rs")
    _write(tmp_path, "tests/user_service_test.rs")
    low = "src/utils/internal/deep/common/shared/service_helper.rs"
    _write(tmp_path, low)

    paths, _ = _ranked_paths(tmp_path)
    for high in ("src/main.rs", "src/routes/users.rs", "src/services/user_service.rs", "tests/user_service_test.rs"):
        _assert_before(paths, high, low)


def test_dotnet_high_value_files_rank_above_deep_utilities(tmp_path: Path) -> None:
    _write(tmp_path, "Rank.csproj", '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>')
    _write(tmp_path, "Program.cs")
    _write(tmp_path, "Controllers/UsersController.cs")
    _write(tmp_path, "Services/UserService.cs")
    _write(tmp_path, "Models/User.cs")
    _write(tmp_path, "Data/UserRepository.cs")
    _write(tmp_path, "Rank.Tests/UserServiceTests.cs")
    low = "src/Utilities/Internal/Deep/Common/user_service_helper.cs"
    _write(tmp_path, low)

    paths, files = _ranked_paths(tmp_path)
    for high in ("Program.cs", "Controllers/UsersController.cs", "Services/UserService.cs", "Rank.Tests/UserServiceTests.cs"):
        _assert_before(paths, high, low)
    assert files["Program.cs"].score > files[low].score
    assert ".NET conventional project path" in files["Controllers/UsersController.cs"].reasons


def test_generated_snapshot_and_duplicate_fixture_penalties(tmp_path: Path) -> None:
    _write(tmp_path, "package.json", '{"name":"penalties"}')
    _write(tmp_path, "src/routes/users.ts")
    _write(tmp_path, "examples/routes/users.ts")
    _write(tmp_path, "vendor/routes/users.ts")
    _write(tmp_path, "src/generated/users.generated.ts")
    _write(tmp_path, "src/__snapshots__/users.snapshot.ts")

    paths, files = _ranked_paths(tmp_path)
    assert "src/routes/users.ts" in paths
    assert "examples/routes/users.ts" not in paths
    assert "vendor/routes/users.ts" not in paths
    assert "src/generated/users.generated.ts" not in paths
    assert "src/__snapshots__/users.snapshot.ts" not in paths
    assert "Route or controller implementation" in files["src/routes/users.ts"].reasons
