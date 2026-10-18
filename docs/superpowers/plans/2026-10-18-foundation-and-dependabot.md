# Steward Foundation and Dependabot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (the owner's global rules forbid subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployed GitHub App on Cloudflare Workers (Python) that merges Dependabot patch and minor updates once CI passes, and labels everything else for the owner.

**Architecture:** Pure Python core (`steward.webhooks`, `steward.github`, `steward.dependabot`) with no Workers imports, tested on CPython. Thin adapters in `steward.worker` bind it to the runtime: the `Default` entrypoint verifies and dispatches webhooks; one `MergeQueue` Durable Object per repository serializes evaluation with an `asyncio.Lock`, so two updates can never merge on the same `main`.

**Tech Stack:** Python 3.14 on Python Workers, `uv` + `pywrangler`, `cryptography` (Pyodide-bundled) for RS256, `pydantic` (Pyodide-bundled) for payload validation, pytest + hypothesis, ruff, mypy strict, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-18-steward-design.md`. This plan covers the spec's "Order of work" steps 1 and 2. Steps 3 (standards) and 4 (hub API, weekly report) get their own plans.

## Global Constraints

- Everything written to the repository (code, comments, commits, issues, PRs, branch names) is in English and never names an AI assistant.
- Commits authored as `ismaleonsaenz@gmail.com`; check `git config user.email` before the first commit.
- Issue first, then branch `feature/foundation-and-dependabot`, then one PR with `Closes #<issue>`; never push to `main`.
- Python `>=3.14,<3.15`; `[tool.uv] exclude-newer = "7 days"`; Pyodide-bundled packages (`cryptography`, `pydantic`, `pydantic-core`) pinned to the exact versions the Workers Pyodide runtime bundles, and excluded from the cooldown and from Dependabot, as `Isma-L154/NavalGame` does for pydantic.
- Mirror NavalGame's tooling: same ruff rule set and line length 100, mypy strict with `workers`/`js` treated as opaque, pytest `-m "not integration"` by default.
- Actions pinned by SHA with the version as a comment; `permissions: contents: read` and `concurrency` on every workflow; `persist-credentials: false` on checkout.
- Secrets `APP_ID`, `PRIVATE_KEY`, `WEBHOOK_SECRET`: Worker secrets only, keys without values in `.dev.vars.example`; any missing or unparseable → every route, health included, answers 500.
- Custom domain `steward.cloudils.com`, `workers_dev = false`. **(builder's call, settled)**
- Managed labels exactly: `major-ready`, `major-broken`, `update-broken`. Rebase request comment exactly: `@dependabot rebase`.
- GitHub REST headers on every call: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `User-Agent: steward`.
- Logs never contain secrets, tokens or payload bodies.

## Review Focus

1. **A Dependabot branch with a commit pushed by someone else** → never merged, whatever the CI says. Test in Task 5.
2. **A grouped update with one major among minors, or a commit message without Dependabot metadata** → treated as major. Test in Task 3.
3. **A required check that is configured but never reports** (renamed job) → verdict stays pending, never merges. Test in Task 3.
4. **The same PR evaluated twice** (two workflows finishing seconds apart) → one rebase comment per head commit, and a second evaluation after a merge does nothing. Test in Task 5; the per-repository lock in Task 7.
5. **GitHub still computing `mergeable` (null)** → re-read up to 3 times, then do nothing rather than merge on unknown. Test in Task 5.

---

### Task 1: Repository, tooling, config, health and CI/CD

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `package.json`, `package-lock.json`, `wrangler.toml`, `.python-version`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.dev.vars.example`, `LICENSE` (MIT)
- Create: `src/entry.py`, `src/steward/__init__.py`, `src/steward/config.py`, `src/steward/worker/__init__.py`, `src/steward/worker/entry.py`, `src/steward/worker/headers.py`, `src/steward/worker/responses.py`
- Create: `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, `.github/actions/start-dev-server/action.yml`, `.github/dependabot.yml`
- Create: `docs/superpowers/specs/2026-10-18-steward-design.md`, `docs/superpowers/plans/2026-10-18-foundation-and-dependabot.md` (copied from the scratchpad)
- Test: `tests/conftest.py`, `tests/test_config.py`, `tests/integration/test_health.py`

**Interfaces:**
- Produces: `Config(app_id: str, private_key: RSAPrivateKey, webhook_secret: bytes)` (frozen dataclass), `MissingConfig(Exception)` whose message is the variable name, `load_config(env: Any) -> Config`. `json_response(body: dict[str, Any], status: HTTPStatus) -> Response`, `error_response(code: str, status: HTTPStatus) -> Response`. Fixture `rsa_key -> RSAPrivateKey` and `rsa_pem -> str` in `tests/conftest.py`.

- [ ] **Step 1: Create the repository and the issue**

Create `Isma-L154/Steward` (public, MIT, initialized with a README so `main` has a base commit), then the issue "Bootstrap Steward: CI/CD, App authentication and Dependabot auto-merge" listing the spec's goal 1 as acceptance criteria. Clone, check `git config user.email` is `ismaleonsaenz@gmail.com`, create branch `feature/foundation-and-dependabot`.

- [ ] **Step 2: Tooling files**

`pyproject.toml` copies NavalGame's structure (name `steward`, deps `cryptography==<Pyodide version>`, `pydantic==2.12.5`; dev group `hypothesis`, `mypy`, `pytest`, `pytest-asyncio`, `ruff`, `httpx` for integration tests, `workers-py`, `workers-runtime-sdk`; first-party `steward`, `tests`). `package.json` pins `wrangler` to the version NavalGame uses. `wrangler.toml`:

```toml
name = "steward"
main = "src/entry.py"
compatibility_date = "2026-10-01"
compatibility_flags = ["python_workers"]
workers_dev = false
routes = [{ pattern = "steward.cloudils.com", custom_domain = true }]

[[durable_objects.bindings]]
name = "MERGE_QUEUE"
class_name = "MergeQueue"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["MergeQueue"]

[[ratelimits]]
name = "WEBHOOK_LIMIT"
namespace_id = "1001"
simple = { limit = 120, period = 60 }

[observability]
enabled = true

[dev]
port = 8787
host = "localhost:8787"
```

`MergeQueue` arrives in Task 7; until then `src/entry.py` exports a placeholder `MergeQueue(DurableObject)` whose `fetch` answers 404, so the binding validates. `.dev.vars.example`: `APP_ID=`, `PRIVATE_KEY=`, `WEBHOOK_SECRET=`.

- [ ] **Step 3: Write the failing config tests**

```python
def test_load_config_reads_all_three(rsa_pem): 
    config = load_config(SimpleNamespace(APP_ID="123", PRIVATE_KEY=rsa_pem, WEBHOOK_SECRET="s3cret"))
    assert config.app_id == "123"
    assert config.webhook_secret == b"s3cret"
    assert isinstance(config.private_key, RSAPrivateKey)

@pytest.mark.parametrize("missing", ["APP_ID", "PRIVATE_KEY", "WEBHOOK_SECRET"])
def test_missing_or_blank_variable_is_named(rsa_pem, missing):
    values = {"APP_ID": "123", "PRIVATE_KEY": rsa_pem, "WEBHOOK_SECRET": "s3cret"} | {missing: "  "}
    with pytest.raises(MissingConfig, match=missing):
        load_config(SimpleNamespace(**values))

def test_unparseable_private_key_is_missing_config():
    with pytest.raises(MissingConfig, match="PRIVATE_KEY"):
        load_config(SimpleNamespace(APP_ID="1", PRIVATE_KEY="not a key", WEBHOOK_SECRET="s"))
```

Also an absent attribute (not just blank) raises `MissingConfig`.

- [ ] **Step 4: Run, expect FAIL** — `uv run pytest tests/test_config.py -v` → ImportError.

- [ ] **Step 5: Implement `load_config` in `src/steward/config.py`**

`getattr(env, name, None)`, strip, `load_pem_private_key(pem.encode(), password=None)`; anything other than an RSA key is `MissingConfig("PRIVATE_KEY")`.

- [ ] **Step 6: Health route and headers**

`headers.py`: NavalGame's header set with CSP `default-src 'none'; frame-ancestors 'none'; base-uri 'none'` (no HTML is ever served) plus `Cache-Control: no-store`. `entry.py`: `Default.fetch` loads config first (on `MissingConfig` print the name and answer 500 `misconfigured`), then `GET /health` → `{"status": "ok", "version": BUILD_VERSION or "dev"}`; any other path 404, wrong method 405.

- [ ] **Step 7: Run unit tests, expect PASS** — `uv run pytest -v`.

- [ ] **Step 8: CI/CD and Dependabot**

Copy NavalGame's `ci.yml` with jobs `lint`, `test`, `semgrep` (`--config p/default --config p/python`) and `worker`, dropping the frontend and e2e parts. Copy its `deploy.yml` with URL `https://steward.cloudils.com` and the health smoke test only. `start-dev-server` writes `.dev.vars` instead of copying the example:

```bash
{
  echo "APP_ID=1"
  echo "WEBHOOK_SECRET=ci-webhook-secret"
  printf 'PRIVATE_KEY="%s"\n' "$(openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048)"
} > .dev.vars
```

and polls `http://localhost:8787/health`. The `worker` job exports `STEWARD_BASE_URL=http://localhost:8787` and `STEWARD_WEBHOOK_SECRET=ci-webhook-secret` for the integration tests. `dependabot.yml` copies NavalGame's (uv, github-actions, npm), ignoring `cryptography`, `pydantic`, `pydantic-core`.

- [ ] **Step 9: Integration test for health**

```python
@pytest.mark.integration
def test_health_reports_version():
    response = httpx.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-content-type-options"] == "nosniff"
```

This also proves `cryptography` imports and parses a key inside `workerd`, since health only answers 200 with valid config.

- [ ] **Step 10: Verify locally** — `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`, then `uv run pywrangler deploy --dry-run --outdir .wrangler/dry-run` succeeds, then start the dev server as the action does and run `uv run pytest -m integration`. All green.

- [ ] **Step 11: Commit** — `git commit -m "chore: bootstrap Steward with tooling, health route and CI/CD"`, push the branch, open the PR as a draft with `Closes #<issue>` so CI runs on every following commit.

---

### Task 2: Webhook signature and payload parsing

**Files:**
- Create: `src/steward/github/__init__.py`, `src/steward/github/models.py`, `src/steward/webhooks/__init__.py`, `src/steward/webhooks/signature.py`, `src/steward/webhooks/events.py`
- Test: `tests/webhooks/test_signature.py`, `tests/webhooks/test_events.py`, `tests/fixtures/workflow_run_completed.json` (a real payload, trimmed, from GitHub's docs)

**Interfaces:**
- Produces: `RepoRef(owner: str, name: str)` with property `full_name -> str` (frozen dataclass, in `models.py`). `is_valid_signature(secret: bytes, body: bytes, header: str | None) -> bool`. `MAX_BODY_BYTES = 1_048_576`. `InvalidPayload(Exception)`. `PullRequestToEvaluate(installation_id: int, repo: RepoRef, number: int)` (frozen). `pull_requests_to_evaluate(event: str, body: str) -> list[PullRequestToEvaluate]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_valid_signature_accepted():
    body = b'{"zen":"hi"}'
    header = "sha256=" + hmac.new(b"k", body, hashlib.sha256).hexdigest()
    assert is_valid_signature(b"k", body, header)

@pytest.mark.parametrize("header", [None, "", "sha256=", "sha1=abc", "sha256=" + "0" * 64])
def test_bad_signatures_rejected(header):
    assert not is_valid_signature(b"k", b"{}", header)

def test_completed_run_yields_its_dependabot_prs(workflow_run_body):
    assert pull_requests_to_evaluate("workflow_run", workflow_run_body) == [
        PullRequestToEvaluate(installation_id=42, repo=RepoRef("Isma-L154", "nextsode"), number=7)
    ]

def test_non_dependabot_branches_are_skipped(workflow_run_body_with_feature_branch):
    assert pull_requests_to_evaluate("workflow_run", workflow_run_body_with_feature_branch) == []

@pytest.mark.parametrize(("event", "action"), [("workflow_run", "requested"), ("push", None), ("ping", None)])
def test_other_events_and_actions_yield_nothing(event, action, ...): ...

@pytest.mark.parametrize("body", ["not json", "[]", '{"action":"completed"}', '{"action":"completed","installation":{"id":"42"}}'])
def test_malformed_completed_run_raises(body):
    with pytest.raises(InvalidPayload):
        pull_requests_to_evaluate("workflow_run", body)
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

`signature.py`: `hmac.compare_digest` on the hex digest after the `sha256=` prefix. `events.py`: pydantic models with `strict=True`, `extra="ignore"` (GitHub payloads carry hundreds of fields), reading only `action`, `installation.id`, `repository.owner.login`, `repository.name`, `workflow_run.pull_requests[].number` and `.head.ref`; keep PRs whose `head.ref` starts with `dependabot/`. Any `ValidationError` or JSON error → `InvalidPayload`.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** — `feat: verify webhook signatures and parse completed workflow runs`.

---

### Task 3: Update type and CI verdict

**Files:**
- Create: `src/steward/dependabot/__init__.py`, `src/steward/dependabot/update_type.py`, `src/steward/dependabot/verdict.py`
- Modify: `src/steward/github/models.py` (add check types)
- Test: `tests/dependabot/test_update_type.py`, `tests/dependabot/test_verdict.py`

**Interfaces:**
- Produces: `UpdateType(StrEnum)`: `PATCH`, `MINOR`, `MAJOR`. `classify(commit_message: str) -> UpdateType`. In `models.py`: `CheckState(StrEnum)`: `SUCCESS`, `FAILURE`, `PENDING`; `CheckResult(name: str, state: CheckState)` (frozen). `Verdict(StrEnum)`: `GREEN`, `RED`, `PENDING`. `ci_verdict(results: Sequence[CheckResult], required: frozenset[str]) -> Verdict`.

- [ ] **Step 1: Write the failing tests**

Dependabot puts a metadata block in the commit message; `classify` reads it:

```python
SINGLE_MINOR = """Bump httpx from 0.27.0 to 0.28.1

---
updated-dependencies:
- dependency-name: httpx
  dependency-version: 0.28.1
  dependency-type: direct:development
  update-type: version-update:semver-minor
...

Signed-off-by: dependabot[bot] <support@github.com>"""

def test_single_minor(): assert classify(SINGLE_MINOR) == UpdateType.MINOR
def test_single_patch(): ...  # semver-patch → PATCH
def test_group_takes_the_largest(): ...  # patch + minor + major entries → MAJOR
def test_group_of_minor_and_patch_is_minor(): ...
def test_no_metadata_is_major(): assert classify("Bump x from 1 to 2") == UpdateType.MAJOR
def test_entry_without_update_type_makes_it_major(): ...  # 2 dependency-name lines, 1 update-type
def test_unknown_update_type_is_major(): ...  # "update-type: version-update:semver-weird"

def test_all_success_with_required_present_is_green():
    results = [CheckResult("lint", CheckState.SUCCESS), CheckResult("test", CheckState.SUCCESS)]
    assert ci_verdict(results, frozenset({"test"})) == Verdict.GREEN

def test_any_failure_is_red_even_if_others_pending(): ...
def test_any_pending_is_pending(): ...
def test_required_check_never_reported_is_pending():
    assert ci_verdict([CheckResult("lint", CheckState.SUCCESS)], frozenset({"test"})) == Verdict.PENDING
def test_no_results_is_pending(): assert ci_verdict([], frozenset()) == Verdict.PENDING
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

`classify`: take the text between the line `---` and the line `...`; count `dependency-name:` entries and `update-type: version-update:semver-(patch|minor|major)` matches by regex. Zero entries, a count mismatch, or any other `update-type` value → `MAJOR`; otherwise the largest. No YAML dependency. `ci_verdict`: failure wins, then pending, then a missing required name is pending, then an empty list is pending, else green.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** — `feat: classify Dependabot updates and compute the CI verdict`.

---

### Task 4: The decision

**Files:**
- Create: `src/steward/dependabot/decision.py`
- Test: `tests/dependabot/test_decision.py`

**Interfaces:**
- Consumes: `UpdateType`, `Verdict` (Task 3).
- Produces: `MAJOR_READY = "major-ready"`, `MAJOR_BROKEN = "major-broken"`, `UPDATE_BROKEN = "update-broken"`, `MANAGED_LABELS: frozenset[str]`. `Kind(StrEnum)`: `NOTHING`, `LABEL`, `REQUEST_REBASE`, `MERGE`. `Decision(kind: Kind, label: str | None = None)` (frozen). `Facts(authored_by_dependabot: bool, open: bool, update_type: UpdateType, verdict: Verdict, has_required_checks: bool, mergeable: bool | None, behind_by: int, rebase_requested: bool)` (frozen). `decide(facts: Facts) -> Decision`.

- [ ] **Step 1: Write the failing tests**

One test per row, plus the invariant as a property test:

| Facts | Decision |
|---|---|
| not authored by Dependabot, or not open (closed or draft) | `NOTHING` |
| major, green | `LABEL major-ready` |
| major, red | `LABEL major-broken` |
| major, pending | `NOTHING` |
| patch/minor, red | `LABEL update-broken` |
| patch/minor, pending | `NOTHING` |
| patch/minor, green, no required checks | `NOTHING` |
| patch/minor, green, `mergeable` False or None | `NOTHING` |
| patch/minor, green, behind, rebase not yet requested | `REQUEST_REBASE` |
| patch/minor, green, behind, rebase already requested | `NOTHING` |
| patch/minor, green, required checks, mergeable, up to date | `MERGE` |

```python
@given(st.builds(Facts, update_type=st.sampled_from(UpdateType), verdict=st.sampled_from(Verdict), ...))
def test_merge_only_for_green_dependabot_minor_or_patch_with_required_checks(facts):
    if decide(facts).kind is Kind.MERGE:
        assert facts.update_type is not UpdateType.MAJOR
        assert facts.verdict is Verdict.GREEN
        assert facts.authored_by_dependabot and facts.open and facts.has_required_checks
        assert facts.mergeable is True and facts.behind_by == 0
```

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `decide` as the table above, top row first.**
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat: decide what to do with a Dependabot pull request`.

---

### Task 5: The Dependabot service

**Files:**
- Create: `src/steward/dependabot/ports.py`, `src/steward/dependabot/service.py`
- Modify: `src/steward/github/models.py` (add PR and commit types)
- Test: `tests/dependabot/fakes.py`, `tests/dependabot/test_service.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces, in `models.py`: `PullRequest(number: int, state: str, draft: bool, author: str, head_sha: str, base_ref: str, mergeable: bool | None, labels: frozenset[str])`, `Commit(author: str | None, message: str)`, `MergeMethod = Literal["squash", "merge", "rebase"]`. In `ports.py`:

```python
class DependabotGitHub(Protocol):
    async def pull_request(self, repo: RepoRef, number: int) -> PullRequest: ...
    async def pull_request_commits(self, repo: RepoRef, number: int) -> list[Commit]: ...
    async def required_checks(self, repo: RepoRef, branch: str) -> frozenset[str]: ...
    async def check_results(self, repo: RepoRef, sha: str) -> list[CheckResult]: ...
    async def behind_by(self, repo: RepoRef, base_ref: str, head_sha: str) -> int: ...
    async def merge_method(self, repo: RepoRef) -> MergeMethod: ...
    async def approve(self, repo: RepoRef, number: int, sha: str) -> None: ...
    async def merge(self, repo: RepoRef, number: int, sha: str, method: MergeMethod) -> bool: ...
    async def add_label(self, repo: RepoRef, number: int, label: str) -> None: ...
    async def remove_label(self, repo: RepoRef, number: int, label: str) -> None: ...
    async def comment(self, repo: RepoRef, number: int, body: str) -> None: ...

class RebaseMemory(Protocol):
    async def was_requested(self, repo: RepoRef, number: int, head_sha: str) -> bool: ...
    async def remember(self, repo: RepoRef, number: int, head_sha: str) -> None: ...
```

`DEPENDABOT_LOGIN = "dependabot[bot]"`, `REBASE_COMMENT = "@dependabot rebase"`, `DependabotService(github: DependabotGitHub, memory: RebaseMemory, sleep: Callable[[float], Awaitable[None]])` with `async evaluate(repo: RepoRef, number: int) -> Decision`.

- [ ] **Step 1: Write the failing tests** against an in-memory `FakeGitHub` that records every write call and a `FakeMemory`:

```python
async def test_green_minor_is_approved_then_merged_with_the_head_sha(): 
    github = FakeGitHub(pr=dependabot_pr(head_sha="abc"), commits=[minor_commit()], required={"test"},
                        checks=[success("test")], behind=0, method="squash")
    decision = await DependabotService(github, FakeMemory(), no_sleep).evaluate(REPO, 7)
    assert decision == Decision(Kind.MERGE)
    assert github.writes == [("approve", 7, "abc"), ("merge", 7, "abc", "squash")]

async def test_extra_commit_by_someone_else_blocks_everything():  # Review Focus 1
    github = FakeGitHub(..., commits=[minor_commit(), Commit(author="Isma-L154", message="tweak")])
    assert (await service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.writes == []

async def test_merge_clears_a_stale_update_broken_label(): ...  # remove_label before approve
async def test_major_green_gets_major_ready_and_loses_major_broken(): ...
async def test_label_already_present_is_not_added_again(): ...
async def test_behind_requests_rebase_once_per_head_sha():  # Review Focus 4
    memory = FakeMemory()
    await service(github_behind, memory).evaluate(REPO, 7)
    await service(github_behind, memory).evaluate(REPO, 7)
    assert github_behind.writes.count(("comment", 7, "@dependabot rebase")) == 1

async def test_already_merged_pr_does_nothing(): ...  # state "closed" → no writes
async def test_unknown_mergeable_is_reread_three_times_then_nothing():  # Review Focus 5
    github = FakeGitHub(..., mergeable_sequence=[None, None, None, None])
    assert (await service(github).evaluate(REPO, 7)).kind is Kind.NOTHING
    assert github.pull_request_reads == 4

async def test_mergeable_resolving_on_reread_merges(): ...  # [None, True] → MERGE
async def test_failed_merge_call_is_reported_not_raised(): ...  # merge returns False → Decision(MERGE) still returned, logged
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement `DependabotService.evaluate`**

Read the PR; re-read it while `mergeable` is None, at most 3 more times with `sleep(1.0)` between. Stop with `NOTHING` before any further call when the PR author is not `DEPENDABOT_LOGIN`. Then read commits (Dependabot-authored = every commit's author is `DEPENDABOT_LOGIN`), the classification of the first commit's message, required checks for `base_ref`, check results for `head_sha`, `behind_by`, and the rebase memory; build `Facts`, `decide`, then apply. `LABEL x`: add `x` if absent, remove the other managed labels present. `MERGE`: remove managed labels present, approve, merge with `merge_method`, print the outcome. `REQUEST_REBASE`: comment, then remember.

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat: evaluate and act on Dependabot pull requests`.

---

### Task 6: GitHub App authentication and REST client

**Files:**
- Create: `src/steward/github/http.py`, `src/steward/github/app_auth.py`, `src/steward/github/client.py`
- Test: `tests/github/fake_http.py`, `tests/github/test_app_auth.py`, `tests/github/test_client.py`

**Interfaces:**
- Consumes: `RepoRef`, `PullRequest`, `Commit`, `CheckResult`, `CheckState`, `MergeMethod` (Tasks 2, 3, 5), `DependabotGitHub` (Task 5).
- Produces:

```python
@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str

class HttpClient(Protocol):
    async def request(self, method: str, url: str, headers: Mapping[str, str], body: str | None = None) -> HttpResponse: ...

class GitHubError(Exception):  # carries status and path, never the token
    def __init__(self, status: int, path: str) -> None: ...

def app_jwt(app_id: str, key: RSAPrivateKey, now: int) -> str
class InstallationTokens:
    def __init__(self, http: HttpClient, app_id: str, key: RSAPrivateKey, clock: Callable[[], float]) -> None: ...
    async def token(self, installation_id: int) -> str: ...

class GitHubClient:  # satisfies DependabotGitHub
    def __init__(self, http: HttpClient, tokens: InstallationTokens, installation_id: int) -> None: ...
```

- [ ] **Step 1: Write the failing tests** against a `FakeHttp` that maps `(method, path)` to canned responses and records requests:

```python
def test_app_jwt_is_rs256_with_backdated_iat_and_ten_minute_cap(rsa_key):
    token = app_jwt("123", rsa_key, now=1_000_000)
    header, payload, signature = token.split(".")
    assert json.loads(b64url_decode(header)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(b64url_decode(payload)) == {"iat": 999_940, "exp": 1_000_540, "iss": "123"}
    rsa_key.public_key().verify(b64url_decode(signature), f"{header}.{payload}".encode(), PKCS1v15(), SHA256())

async def test_installation_token_is_cached_until_five_minutes_before_expiry(): ...
async def test_installation_token_refreshed_after_that(): ...
async def test_required_checks_union_rulesets_and_classic_protection(): ...
async def test_required_checks_tolerates_404_from_classic_protection(): ...
async def test_check_runs_and_statuses_map_to_states():
    # check run completed+success/neutral/skipped → SUCCESS; completed+anything else → FAILURE;
    # not completed → PENDING; status success → SUCCESS, pending → PENDING, failure/error → FAILURE
async def test_merge_returns_false_on_405_and_409(): ...
async def test_merge_sends_sha_and_method(): ...
async def test_remove_label_ignores_404(): ...
async def test_merge_method_prefers_squash_then_merge_then_rebase(): ...
async def test_unexpected_status_raises_github_error_without_token_in_message(): ...
async def test_every_request_carries_the_api_headers(): ...
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

JWT by hand: base64url without padding, signature `key.sign(signing_input, PKCS1v15(), SHA256())`; no JWT library. Token: `POST /app/installations/{id}/access_tokens` with `Authorization: Bearer <jwt>`; cache per installation until `expires_at - 300 s`. Endpoints (base `https://api.github.com`, `per_page=100`, no pagination: a Dependabot PR has far fewer than 100 commits or checks):

| Method | Endpoint |
|---|---|
| `pull_request` | `GET /repos/{full}/pulls/{n}` |
| `pull_request_commits` | `GET /repos/{full}/pulls/{n}/commits` (`author.login`, null author → None) |
| `required_checks` | `GET /repos/{full}/rules/branches/{branch}` (rules of type `required_status_checks`) ∪ `GET /repos/{full}/branches/{branch}/protection/required_status_checks` (`contexts` and `checks[].context`; 404 → none) |
| `check_results` | `GET /repos/{full}/commits/{sha}/check-runs` + `GET /repos/{full}/commits/{sha}/status` |
| `behind_by` | `GET /repos/{full}/compare/{base_ref}...{head_sha}` |
| `merge_method` | `GET /repos/{full}` (`allow_squash_merge`, `allow_merge_commit`, `allow_rebase_merge`; an absent field counts as allowed) |
| `approve` | `POST /repos/{full}/pulls/{n}/reviews` `{"commit_id": sha, "event": "APPROVE"}` |
| `merge` | `PUT /repos/{full}/pulls/{n}/merge` `{"sha": sha, "merge_method": method}` |
| `add_label` / `remove_label` | `POST /repos/{full}/issues/{n}/labels` / `DELETE .../labels/{quoted name}` |
| `comment` | `POST /repos/{full}/issues/{n}/comments` |

- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat: authenticate as the GitHub App and call the REST API`.

---

### Task 7: Worker adapters and the webhook route

**Files:**
- Create: `src/steward/worker/fetch_http.py`, `src/steward/worker/merge_queue.py`, `src/steward/worker/rebase_memory.py`
- Modify: `src/steward/worker/entry.py`, `src/entry.py` (export the real `MergeQueue`), `pyproject.toml` (mypy subclassing override for the adapter modules, as NavalGame does)
- Test: `tests/integration/test_webhook.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `WorkersFetch` (satisfies `HttpClient`, wraps `workers.fetch`); `DurableObjectRebaseMemory(storage: Any)` (satisfies `RebaseMemory`, keys `rebase:{number}:{head_sha}`); `MergeQueue(DurableObject)` answering `POST /evaluate` with body `{"installation_id": int, "owner": str, "name": str, "number": int}` and replying `{"decision": "<kind>"}`.

- [ ] **Step 1: Write the failing integration tests** (marked `integration`, run against the dev server from Task 1):

```python
def sign(body: bytes) -> str: return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()

def test_unsigned_webhook_is_401(): assert post("/webhook", b"{}", event="ping").status_code == 401
def test_wrongly_signed_webhook_is_401(): ...
def test_signed_ping_is_200(): assert post("/webhook", b'{"zen":"x"}', event="ping", signed=True).status_code == 200
def test_body_over_limit_is_413(): ...  # declared Content-Length MAX_BODY_BYTES + 1
def test_signed_malformed_workflow_run_is_400(): ...
def test_signed_workflow_run_for_feature_branch_is_202_with_nothing_queued(): ...  # {"queued": 0}
def test_get_on_webhook_is_405(): ...
def test_unknown_path_is_404(): ...
```

- [ ] **Step 2: Run against the dev server, expect FAIL.**

- [ ] **Step 3: Implement**

Order on `POST /webhook`: config → rate limit (`await env.WEBHOOK_LIMIT.limit(key=<CF-Connecting-IP>)`, `success` false → 429) → declared `Content-Length` over `MAX_BODY_BYTES` or absent → 413 → read body → signature → 401 → `X-GitHub-Event` `ping` → 200 → `pull_requests_to_evaluate` (`InvalidPayload` → 400) → for each, `await env.MERGE_QUEUE.getByName(repo.full_name).fetch("https://queue/evaluate", method="POST", body=...)` → 202 `{"queued": n}`. Evaluations are awaited, not deferred: one takes a few seconds, well inside GitHub's 10-second delivery timeout. `MergeQueue` holds an `asyncio.Lock` on the instance and runs `DependabotService.evaluate` inside it, keeping one `InstallationTokens` per instance so tokens are reused; `GitHubError` is printed (status and path only) and answered 502. `WorkersFetch` returns `HttpResponse(status, await response.text())`.

- [ ] **Step 4: Run all checks** — lint, mypy, unit tests, dry-run bundle, integration tests against the dev server. All green.
- [ ] **Step 5: Commit** — `feat: receive webhooks and serialize evaluations per repository`.

---

### Task 8: Docs, security review, merge and go live

**Files:**
- Create: `AGENTS.md`, `CLAUDE.md` (imports `AGENTS.md`), `SECURITY.md`
- Modify: `README.md`, `docs/brand/` (banner)

- [ ] **Step 1: `AGENTS.md`** with the `init-agent-rules` skill; the seven controls as decided in the spec's security baseline table.
- [ ] **Step 2: README** with the `docs-sync` skill: banner, badges, Mermaid diagram (GitHub → `/webhook` → `MergeQueue` per repo → GitHub API), setup including the manual App registration in Step 5.
- [ ] **Step 3: `security-scan` skill** over the branch; fix anything it finds that applies.
- [ ] **Step 4: Review the whole branch myself** (`superpowers:requesting-code-review` checklist, inline, no subagent) against the spec and this plan's Review Focus; then mark the PR ready, wait for green CI, merge, `git switch main && git pull`, delete the branch.
- [ ] **Step 5: Owner registers the App** (manual, guided): GitHub → Settings → Developer settings → GitHub Apps → New. Webhook URL `https://steward.cloudils.com/webhook`, a generated secret; permissions Metadata read, Contents read/write, Pull requests read/write, Issues read/write, Checks read, Commit statuses read, Actions read, Administration read; event "Workflow run"; installable only on this account. Generate the private key. Then `uv run pywrangler secret put APP_ID`, `PRIVATE_KEY`, `WEBHOOK_SECRET`.
- [ ] **Step 6: Verify live** — `/health` answers 200 with the merged commit as version; GitHub's "Recent deliveries" shows the ping as 200. Install the App on **one** repository that has a pending Dependabot minor update and required checks, re-run that PR's CI, and confirm: approved and merged by the App, or the expected label/comment, with the decision visible in Workers logs. Only then install on the rest.
