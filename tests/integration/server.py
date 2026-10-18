import os

BASE_URL = os.environ.get("STEWARD_BASE_URL", "http://localhost:8787")
# The first request to a freshly started Python Worker can take several seconds.
TIMEOUT = 30.0
