import re

from steward.standards.snapshot import Finding, RepoSnapshot

# The README standard of the docs-sync skill (Isma-L154/agent-skills).
_BANNER = re.compile(
    r"<img[^>]+src=[\"'][^\"']*docs/brand/banner|!\[[^\]]*\]\([^)]*docs/brand/banner"
)
_HEADING = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
_REQUIRED = ("What it does", "How it works", "License")
_SPELLINGS = {"Licence": "License"}
_ORDER = {
    "What it does": 0,
    "How it works": 1,
    "Running locally": 2,
    "Installation": 2,
    "Usage": 2,
    "Deployment": 3,
    "Security": 4,
    "License": 5,
}
_CONTROLS = range(1, 8)
_BASELINE = re.compile(
    r"^#+ .*(?:Baseline security controls|Security baseline).*$", re.MULTILINE | re.IGNORECASE
)


def check_readme(snapshot: RepoSnapshot) -> list[Finding]:
    text = snapshot.readme
    if text is None:
        return [Finding("readme", "`README.md` is missing")]
    missing = []
    if not _BANNER.search(text):
        missing.append("the drawn banner (`docs/brand/banner`)")
    if "img.shields.io" not in text and "/badge.svg" not in text:
        missing.append("status badges")
    if "```mermaid" not in text:
        missing.append("the Mermaid architecture diagram")
    # A README covering several tools repeats the sections once per tool, so the order is
    # read from where each section first appears.
    headings = dict.fromkeys(_SPELLINGS.get(h, h) for h in _HEADING.findall(text))
    missing += [f"the `{section}` section" for section in _REQUIRED if section not in headings]
    ranks = [_ORDER[heading] for heading in headings if heading in _ORDER]
    if ranks != sorted(ranks):
        missing.append("the standard section order")
    if not missing:
        return []
    return [Finding("readme", "`README.md` lacks " + ", ".join(missing))]


def check_agents(snapshot: RepoSnapshot) -> list[Finding]:
    # Public repositories may keep AGENTS.md out of git as local tooling; SECURITY.md then
    # carries the controls.
    documents = (("AGENTS.md", snapshot.agents), ("SECURITY.md", snapshot.security))
    located = next(
        (
            (name, text, heading)
            for name, text in documents
            if text is not None and (heading := _BASELINE.search(text))
        ),
        None,
    )
    if located is None:
        return [
            Finding(
                "agents",
                "Neither `AGENTS.md` nor `SECURITY.md` has a baseline security controls section",
            )
        ]
    name, text, heading = located
    section = text[heading.end() :]
    decided = {
        int(number)
        for number, line in re.findall(r"^(\d)\. (.*)$", section, re.MULTILINE)
        if re.search(r"\bimplemented\b|\bN/A\b", line, re.IGNORECASE)
    }
    undecided = [str(number) for number in _CONTROLS if number not in decided]
    if not undecided:
        return []
    return [
        Finding(
            "agents",
            f"`{name}` does not decide baseline control(s) " + ", ".join(undecided),
        )
    ]
