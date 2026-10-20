import pytest
import yaml

from steward.standards.dependabot_config import check_dependabot
from steward.standards.rules import run_checks
from steward.standards.yaml_files import MAX_YAML_BYTES, load_yaml
from tests.standards.builders import CI, DEPENDABOT, OWNER_EMAIL, snapshot


@pytest.fixture
def parsed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    texts: list[str] = []
    real = yaml.safe_load

    def spy(text: str) -> object:
        texts.append(text)
        return real(text)

    monkeypatch.setattr(yaml, "safe_load", spy)
    return texts


def _oversized(text: str) -> str:
    return text + "#" * (MAX_YAML_BYTES - len(text.encode()) + 1) + "\n"


def test_cap_is_64_kib() -> None:
    assert MAX_YAML_BYTES == 64 * 1024


def test_text_at_the_cap_is_parsed() -> None:
    text = "a: 1\n#" + "x" * (MAX_YAML_BYTES - 7) + "\n"
    assert len(text.encode()) == MAX_YAML_BYTES
    assert load_yaml(text) == {"a": 1}


def test_cap_counts_bytes_not_characters(parsed: list[str]) -> None:
    text = "a: 1\n#" + "é" * (MAX_YAML_BYTES // 2) + "\n"
    assert load_yaml(text) is None
    assert parsed == []


def test_invalid_yaml_is_none() -> None:
    assert load_yaml("on: [unclosed\n") is None


def test_oversized_workflow_is_unreadable_and_never_parsed(parsed: list[str]) -> None:
    big = _oversized(CI)
    repo = snapshot(workflows={"ci.yml": CI, "big.yml": big})
    findings = run_checks(repo, OWNER_EMAIL, frozenset())
    assert [f.rule for f in findings if f.rule == "workflow-unreadable"] == ["workflow-unreadable"]
    assert "`big.yml`" in next(f.detail for f in findings if f.rule == "workflow-unreadable")
    assert big not in parsed


def test_oversized_dependabot_cannot_be_read_and_is_never_parsed(parsed: list[str]) -> None:
    big = _oversized(DEPENDABOT)
    findings = check_dependabot(snapshot(dependabot=big))
    assert [f.detail for f in findings] == ["`.github/dependabot.yml` cannot be read"]
    assert big not in parsed
