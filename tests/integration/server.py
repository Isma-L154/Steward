import os

BASE_URL = os.environ.get("STEWARD_BASE_URL", "http://localhost:8787")
# The stand-in hub (tests/integration/caller) that reaches HubApi through service bindings.
CALLER_URL = os.environ.get("STEWARD_CALLER_URL", "http://localhost:8788")
# The first request to a freshly started Python Worker can take several seconds.
TIMEOUT = 30.0
