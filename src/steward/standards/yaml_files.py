from typing import Any

import yaml

# Repository files are untrusted input to an audit with a CPU limit; a real workflow or
# Dependabot file is a few KiB.
MAX_YAML_BYTES = 64 * 1024


def load_yaml(text: str) -> Any | None:
    """The parsed document, or None when the file is too large to parse or is not YAML."""
    if len(text.encode()) > MAX_YAML_BYTES:
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return None
