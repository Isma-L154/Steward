import re

from steward.standards.docs import check_agents, check_readme
from tests.standards.builders import ROOT, snapshot

README = (ROOT / "README.md").read_text(encoding="utf-8")
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


def test_stewards_own_docs_pass() -> None:
    assert check_readme(snapshot()) == []
    assert check_agents(snapshot()) == []


def test_missing_readme_is_reported() -> None:
    assert [f.rule for f in check_readme(snapshot(readme=None))] == ["readme"]


def test_readme_without_mermaid_names_the_diagram() -> None:
    findings = check_readme(snapshot(readme=README.replace("```mermaid", "```text")))
    assert [f.rule for f in findings] == ["readme"]
    assert "diagram" in findings[0].detail


def test_readme_without_banner_or_badges_lists_both() -> None:
    bare = (
        README.replace("docs/brand/banner", "x")
        .replace("badge.svg", "x")
        .replace("img.shields.io", "x")
    )
    findings = check_readme(snapshot(readme=bare))
    assert len(findings) == 1
    assert "banner" in findings[0].detail
    assert "badge" in findings[0].detail


def test_readme_missing_a_required_section_names_it() -> None:
    findings = check_readme(snapshot(readme=README.replace("## How it works", "## Internals")))
    assert "`How it works`" in findings[0].detail


def test_readme_sections_out_of_order_are_reported() -> None:
    swapped = README.replace("## Security", "## TEMP").replace("## License", "## Security")
    swapped = swapped.replace("## TEMP", "## License")
    findings = check_readme(snapshot(readme=swapped))
    assert "order" in findings[0].detail


def test_missing_agents_is_reported() -> None:
    assert [f.rule for f in check_agents(snapshot(agents=None))] == ["agents"]


def test_agents_missing_one_control_names_it() -> None:
    without_six = re.sub(r"(?m)^6\. .*$", "", AGENTS)
    findings = check_agents(snapshot(agents=without_six))
    assert [f.rule for f in findings] == ["agents"]
    assert "6" in findings[0].detail


def test_agents_without_the_baseline_heading_is_reported() -> None:
    findings = check_agents(snapshot(agents=AGENTS.replace("Baseline security controls", "X")))
    assert [f.rule for f in findings] == ["agents"]
