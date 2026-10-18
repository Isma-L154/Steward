from dataclasses import replace
from pathlib import Path
from typing import Any

from steward.github.models import RepoRef
from steward.standards.snapshot import CommitInfo, MergedPr, RepoSnapshot

ROOT = Path(__file__).parent.parent.parent
OWNER_EMAIL = "ismaleonsaenz@gmail.com"
SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"

CI = f"""name: CI
on:
  pull_request:
  workflow_call:
permissions:
  contents: read
concurrency:
  group: ci-${{{{ github.ref }}}}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
      - uses: ./.github/actions/setup
      - run: uv run pytest
"""

DEPLOY = """name: Deploy
on:
  push:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: deploy
jobs:
  ci:
    uses: ./.github/workflows/ci.yml
"""

DEPENDABOT = """version: 2
updates:
  - package-ecosystem: uv
    directory: /
    schedule: {interval: weekly}
  - package-ecosystem: npm
    directory: /
    schedule: {interval: weekly}
  - package-ecosystem: github-actions
    directory: /
    schedule: {interval: weekly}
"""


def commit(**changes: Any) -> CommitInfo:
    base = CommitInfo(
        oid="a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
        message="feat: something useful",
        author_email=OWNER_EMAIL,
        author_login="Isma-L154",
        is_root=False,
        from_merged_pr=True,
    )
    return replace(base, **changes)


def merged_pr(**changes: Any) -> MergedPr:
    base = MergedPr(
        number=12,
        title="Add something useful",
        body="Closes #11",
        head_ref="feature/something",
        author_login="Isma-L154",
        references_issue=True,
    )
    return replace(base, **changes)


def snapshot(**changes: Any) -> RepoSnapshot:
    base = RepoSnapshot(
        repo=RepoRef("Isma-L154", "example"),
        default_branch="main",
        readme=(ROOT / "README.md").read_text(encoding="utf-8"),
        agents=(ROOT / "AGENTS.md").read_text(encoding="utf-8"),
        dependabot=DEPENDABOT,
        workflows={"ci.yml": CI, "deploy.yml": DEPLOY},
        paths=frozenset(
            {
                ".github/workflows/ci.yml",
                ".github/workflows/deploy.yml",
                ".github/dependabot.yml",
                "pyproject.toml",
                "uv.lock",
                "package.json",
                "README.md",
                "AGENTS.md",
            }
        ),
        required_checks=frozenset({"test"}),
        commits=[commit()],
        merged_prs=[merged_pr()],
    )
    return replace(base, **changes)
