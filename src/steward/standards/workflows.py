import re
from collections.abc import Iterator, Mapping
from typing import Any

import yaml

from steward.standards.snapshot import Finding, RepoSnapshot, code_span

_PINNED = re.compile(r"[0-9a-f]{40}|v?\d+(\.\d+)*")


type Workflows = Mapping[str, dict[Any, Any]]


def parse_workflows(snapshot: RepoSnapshot) -> Workflows:
    """The workflow files that parse to a mapping; the others are reported as unreadable."""
    parsed = {}
    for name, text in snapshot.workflows.items():
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(document, dict):
            parsed[name] = document
    return parsed


def _triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key `on` as the boolean True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on: None}
    if isinstance(on, list):
        return dict.fromkeys(map(str, on))
    return on if isinstance(on, dict) else {}


def _pushes_to(trigger: Any, branch: str) -> bool:
    if not isinstance(trigger, dict):
        return True
    branches = trigger.get("branches")
    if branches is None:
        return "tags" not in trigger
    return branch in branches or "*" in branches or "**" in branches


def check_ci_triggers(snapshot: RepoSnapshot, workflows: Workflows) -> list[Finding]:
    unreadable = [
        Finding("workflow-unreadable", f"{code_span(name)} is not a valid workflow file")
        for name in sorted(set(snapshot.workflows) - set(workflows))
    ]
    triggers = [_triggers(workflow) for workflow in workflows.values()]
    on_pull_request = any("pull_request" in trigger for trigger in triggers)
    on_main = any(
        "push" in trigger and _pushes_to(trigger["push"], snapshot.default_branch)
        for trigger in triggers
    )
    missing = [
        label
        for label, present in (("pull requests", on_pull_request), ("pushes to main", on_main))
        if not present
    ]
    if not missing:
        return unreadable
    return [*unreadable, Finding("ci-triggers", "No workflow runs on " + " or ".join(missing))]


def _uses(workflow: dict[Any, Any]) -> Iterator[str]:
    jobs = workflow.get("jobs")
    for job in jobs.values() if isinstance(jobs, dict) else ():
        if not isinstance(job, dict):
            continue
        if isinstance(job.get("uses"), str):
            yield job["uses"]
        for step in job.get("steps") or ():
            if isinstance(step, dict) and isinstance(step.get("uses"), str):
                yield step["uses"]


def _is_pinned(reference: str) -> bool:
    # `$/` is GitHub's self-repository form: it resolves at the workflow's own commit.
    if reference.startswith(("./", "$/", "docker://")):
        return True
    _, separator, ref = reference.partition("@")
    return bool(separator) and _PINNED.fullmatch(ref) is not None


def check_actions_pinned(workflows: Workflows) -> list[Finding]:
    findings = []
    for name, workflow in sorted(workflows.items()):
        loose = sorted({ref for ref in _uses(workflow) if not _is_pinned(ref)})
        if loose:
            listed = ", ".join(map(code_span, loose))
            findings.append(
                Finding("actions-pinned", f"{code_span(name)} uses unpinned actions: {listed}")
            )
    return findings


def check_permissions(workflows: Workflows) -> list[Finding]:
    findings = []
    for name, workflow in sorted(workflows.items()):
        jobs = workflow.get("jobs")
        jobs = jobs if isinstance(jobs, dict) else {}
        every_job = bool(jobs) and all(
            isinstance(job, dict) and "permissions" in job for job in jobs.values()
        )
        if "permissions" not in workflow and not every_job:
            findings.append(Finding("permissions", f"{code_span(name)} declares no permissions"))
    return findings


def check_concurrency(workflows: Workflows) -> list[Finding]:
    return [
        Finding("concurrency", f"{code_span(name)} declares no concurrency")
        for name, workflow in sorted(workflows.items())
        if "concurrency" not in workflow
    ]
