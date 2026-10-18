from steward.standards.dependabot_config import check_dependabot, detected_ecosystems
from tests.standards.builders import DEPENDABOT, snapshot


def test_compliant_dependabot_has_no_findings() -> None:
    assert check_dependabot(snapshot()) == []


def test_ecosystems_are_detected_by_file_name() -> None:
    paths = frozenset(
        {
            "web/package.json",
            "pyproject.toml",
            "src/App/App.csproj",
            "deploy/compose/docker-compose.yml",
            "infra/main.tf",
            "Dockerfile",
            ".github/workflows/ci.yml",
            "node_modules/left-pad/package.json",
        }
    )
    assert detected_ecosystems(paths) == {
        "npm",
        "pip",
        "nuget",
        "docker-compose",
        "terraform",
        "docker",
        "github-actions",
    }


def test_manifests_under_vendored_folders_are_ignored() -> None:
    paths = frozenset({"node_modules/a/package.json", ".venv/lib/pyproject.toml"})
    assert detected_ecosystems(paths) == frozenset()


def test_missing_dependabot_file_is_reported() -> None:
    assert [f.rule for f in check_dependabot(snapshot(dependabot=None))] == ["dependabot"]


def test_missing_ecosystem_is_named() -> None:
    no_actions = DEPENDABOT.replace("package-ecosystem: github-actions", "package-ecosystem: cargo")
    findings = check_dependabot(snapshot(dependabot=no_actions))
    assert [f.rule for f in findings] == ["dependabot"]
    assert "`github-actions`" in findings[0].detail


def test_pip_entry_also_covers_python_manifests() -> None:
    with_pip = DEPENDABOT.replace("package-ecosystem: uv", "package-ecosystem: pip")
    assert check_dependabot(snapshot(dependabot=with_pip)) == []


def test_unreadable_dependabot_file_is_reported() -> None:
    assert [f.rule for f in check_dependabot(snapshot(dependabot="updates: [oops"))] == [
        "dependabot"
    ]
