from fnmatch import fnmatch
from pathlib import PurePosixPath

import yaml

from steward.standards.snapshot import Finding, RepoSnapshot, code_span

_VENDORED = frozenset({"node_modules", "vendor", ".venv", "python_modules"})
_MANIFESTS = (
    ("package.json", "npm"),
    ("pyproject.toml", "pip"),
    ("requirements*.txt", "pip"),
    ("uv.lock", "pip"),
    ("Cargo.toml", "cargo"),
    ("go.mod", "gomod"),
    ("*.csproj", "nuget"),
    ("*.sln", "nuget"),
    ("pom.xml", "maven"),
    ("build.gradle", "gradle"),
    ("build.gradle.kts", "gradle"),
    ("composer.json", "composer"),
    ("Gemfile", "bundler"),
    ("Dockerfile", "docker"),
    ("docker-compose.yml", "docker-compose"),
    ("compose.yml", "docker-compose"),
    ("compose.yaml", "docker-compose"),
    ("*.tf", "terraform"),
)
# Dependabot's `uv` ecosystem covers the same Python manifests as `pip`.
_EQUIVALENT = {"uv": "pip"}


def detected_ecosystems(paths: frozenset[str]) -> frozenset[str]:
    found = set()
    for path in paths:
        parts = PurePosixPath(path).parts
        if _VENDORED.intersection(parts[:-1]):
            continue
        if parts[:2] == (".github", "workflows"):
            found.add("github-actions")
        found.update(eco for pattern, eco in _MANIFESTS if fnmatch(parts[-1], pattern))
    return frozenset(found)


def _configured(text: str) -> frozenset[str] | None:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    updates = document.get("updates") if isinstance(document, dict) else None
    if not isinstance(updates, list):
        return None
    names: list[str] = [
        entry["package-ecosystem"]
        for entry in updates
        if isinstance(entry, dict) and isinstance(entry.get("package-ecosystem"), str)
    ]
    return frozenset(_EQUIVALENT.get(name, name) for name in names)


def check_dependabot(snapshot: RepoSnapshot) -> list[Finding]:
    if snapshot.dependabot is None:
        return [Finding("dependabot", "`.github/dependabot.yml` is missing")]
    configured = _configured(snapshot.dependabot)
    if configured is None:
        return [Finding("dependabot", "`.github/dependabot.yml` cannot be read")]
    missing = sorted(detected_ecosystems(snapshot.paths) - configured)
    if not missing:
        return []
    listed = ", ".join(map(code_span, missing))
    return [Finding("dependabot", f"Dependabot does not cover {listed}")]
