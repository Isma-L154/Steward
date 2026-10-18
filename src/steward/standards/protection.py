from steward.standards.snapshot import Finding, RepoSnapshot


def check_required_checks(snapshot: RepoSnapshot) -> list[Finding]:
    if snapshot.required_checks:
        return []
    return [
        Finding(
            "required-checks",
            f"`{snapshot.default_branch}` has no required status checks, so Steward never "
            "merges Dependabot updates here",
        )
    ]
