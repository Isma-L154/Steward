import re

from steward.standards.flow import commit_link, pr_link
from steward.standards.snapshot import Finding, RepoSnapshot

# Only attribution counts: a repository may legitimately talk about these products.
_ASSISTANTS = r"claude|anthropic|codex|openai|gemini|copilot|chatgpt"
_ATTRIBUTION = re.compile(
    rf"^co-authored-by:[^\n]*\b({_ASSISTANTS})\b|generated (with|by)\b[^\n]*\b({_ASSISTANTS})\b",
    re.IGNORECASE | re.MULTILINE,
)
_BRANCH = re.compile(r"^(claude|codex|copilot|cursor|gemini|openai|ai)/", re.IGNORECASE)


def check_no_ai_trace(snapshot: RepoSnapshot) -> list[Finding]:
    findings = [
        Finding("ai-trace", f"Commit {commit_link(snapshot, commit)} carries an AI attribution")
        for commit in snapshot.commits
        if _ATTRIBUTION.search(commit.message)
    ]
    for pr in snapshot.merged_prs:
        if _ATTRIBUTION.search(f"{pr.title}\n{pr.body}"):
            findings.append(
                Finding(
                    "ai-trace", f"Pull request {pr_link(snapshot, pr)} carries an AI attribution"
                )
            )
        if _BRANCH.match(pr.head_ref):
            findings.append(
                Finding(
                    "ai-trace",
                    f"Pull request {pr_link(snapshot, pr)} came from an AI-named branch",
                )
            )
    return findings
