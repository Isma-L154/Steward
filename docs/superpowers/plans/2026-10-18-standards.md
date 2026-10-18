# Steward Standards Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (the owner's global rules forbid subagents). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Steward audits every managed repository against the owner's mechanical rules, on each push to the default branch and in a weekly sweep, and keeps one "Repository standards" issue per repository.

**Architecture:** Pure checks over a `RepoSnapshot` (one GraphQL query plus three REST calls per repository) in `steward.standards`; a `StandardsService` turns findings into one tracking issue. A new `StandardsAudit` Durable Object audits one repository per call, so every audit gets its own budget of 50 GitHub calls on the free plan; the Worker's `scheduled` handler fans the weekly sweep out to it, and push webhooks call it directly.

**Tech Stack:** as phase 1, plus `PyYAML` 6.0.3 (Pyodide-bundled) and the GitHub GraphQL API.

**Spec:** `docs/superpowers/specs/2026-10-18-steward-design.md` ("Standards module", order of work step 3). Issue: #13.

## Global Constraints

- Everything from phase 1's plan (`docs/superpowers/plans/2026-10-18-foundation-and-dependabot.md`) still applies: English, no AI trace, issue → `feature/standards-checks` → PR with `Closes #13`, merged with a **merge commit**; Python 3.14; ruff/mypy strict; `cryptography` never at runtime.
- `pyyaml==6.0.3`, exempt from the uv cooldown and ignored by Dependabot, like `pydantic`.
- A repository is managed unless it is archived or has the topic `steward-ignore` (`IGNORE_TOPIC`). Both modules honour it.
- Weekly cron `0 6 * * 1` (the account uses 2 of 5 cron triggers). At most 50 subrequests per invocation: the sweep makes ≤ 3 GitHub calls plus one Durable Object call per repository; one audit makes ≤ 10 GitHub calls.
- Owner email from the Worker variable `OWNER_EMAIL = "ismaleonsaenz@gmail.com"` in `wrangler.toml` `[vars]`, never hard-coded in code.
- Tracking issue: title exactly `Repository standards`, label `standards`, created by Steward's bot; found again by label + creator, never duplicated.
- Issue bodies contain only Steward's own wording, commit SHAs, PR numbers, rule names and file names wrapped by `code_span()`; never repository free text, never an `@`, never an AI assistant's name.
- Commit and PR checks look at a rolling 30-day window (`WINDOW_DAYS = 30`).
- Bot actors are recognised in both REST and GraphQL forms: `dependabot[bot]` / `dependabot`, `<slug>[bot]` / `<slug>`.

## Review Focus

1. **A repository whose `main` history contains merge commits from feature branches** → the branch commits arrive through a merged PR and must not count as direct pushes. Test in Task 4.
2. **A repository's own initial commit** (no parents, created by GitHub) → not a direct push. Test in Task 4.
3. **Dependabot's and Steward's own PRs** never reference an issue → not flagged by "PR references an issue". Test in Task 4.
4. **A repository that legitimately talks about an AI product** (`OpenAI-Chatbot-through-WhatsApp`) → plain mentions are not attribution traces; only co-author trailers, "generated with/by" lines and AI-prefixed branches are. Test in Task 4.
5. **A file name with backticks, newlines or an `@`** in a finding → rendered inert in the issue body. Test in Task 6.

---

### Task 1: Managed repositories, push events, and the ignore topic

**Files:**
- Create: `src/steward/repos.py`
- Modify: `src/steward/webhooks/events.py`
- Test: `tests/test_repos.py`, `tests/webhooks/test_events.py`, `tests/fixtures/push_main.json`

**Interfaces:**
- Produces: `IGNORE_TOPIC = "steward-ignore"`; `is_managed(archived: bool, topics: Sequence[str]) -> bool`. In `events.py`: `RepoToAudit(installation_id: int, repo: RepoRef)` (frozen); `repos_to_audit(event: str, body: str) -> list[RepoToAudit]` (a `push` to `refs/heads/<repository.default_branch>` of a managed repository → one item; anything else → `[]`; malformed push → `InvalidPayload`). `pull_requests_to_evaluate` also returns `[]` for an unmanaged repository (`repository.archived`, `repository.topics`).

- [ ] **Step 1: Failing tests** — `is_managed(False, [])` is True; `is_managed(True, [])` and `is_managed(False, ["x", "steward-ignore"])` are False. `repos_to_audit("push", <push to main>)` → `[RepoToAudit(42, RepoRef("Isma-L154", "nextsode"))]`; push to `refs/heads/feature/x` → `[]`; push to a `steward-ignore` repository → `[]`; `workflow_run` with `topics: ["steward-ignore"]` → `[]` from `pull_requests_to_evaluate`; push body without `repository.default_branch` → `InvalidPayload`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — strict pydantic models reading `ref`, `installation.id`, `repository.{name, owner.login, default_branch, archived, topics}`; `topics` and `archived` default to `[]`/`False` when GitHub omits them.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** — `feat: skip archived and steward-ignore repositories, and parse pushes to main`.

---

### Task 2: The snapshot and the workflow checks

**Files:**
- Create: `src/steward/standards/__init__.py`, `src/steward/standards/snapshot.py`, `src/steward/standards/workflows.py`
- Modify: `pyproject.toml`, `.github/dependabot.yml`
- Test: `tests/standards/__init__.py`, `tests/standards/builders.py`, `tests/standards/test_workflows.py`

**Interfaces:**
- Produces, in `snapshot.py` (all frozen dataclasses):

```python
@dataclass(frozen=True)
class CommitInfo:
    oid: str
    message: str
    author_email: str
    author_login: str | None
    is_root: bool
    from_merged_pr: bool

@dataclass(frozen=True)
class MergedPr:
    number: int
    title: str
    body: str
    head_ref: str
    author_login: str
    references_issue: bool

@dataclass(frozen=True)
class RepoSnapshot:
    repo: RepoRef
    default_branch: str
    readme: str | None
    agents: str | None
    dependabot: str | None
    workflows: Mapping[str, str]        # file name -> YAML text
    paths: frozenset[str]               # every path in the default branch tree
    required_checks: frozenset[str]
    commits: Sequence[CommitInfo]       # last WINDOW_DAYS on the default branch
    merged_prs: Sequence[MergedPr]      # merged into the default branch in the window

@dataclass(frozen=True)
class Finding:
    rule: str      # e.g. "actions-pinned"
    detail: str    # Steward's own words; file names already through code_span()
```

`WINDOW_DAYS = 30`. `code_span(text: str) -> str` (wraps in single backticks after removing backticks, newlines and `@`). In `workflows.py`: `check_ci_triggers`, `check_actions_pinned`, `check_permissions`, `check_concurrency`, each `(RepoSnapshot) -> list[Finding]`. `tests/standards/builders.py`: `snapshot(**changes) -> RepoSnapshot` returning a fully compliant repository.

- [ ] **Step 1: Add `pyyaml==6.0.3`** to dependencies, to `exclude-newer-package` and to Dependabot's ignore list; `uv run pywrangler sync` succeeds (with `UV_CACHE_DIR`/`UV_PYTHON_INSTALL_DIR` on `D:`).
- [ ] **Step 2: Failing tests** — the compliant builder snapshot yields no findings from any check; then one test per failure:
  - no workflow with `on: pull_request` → `ci-triggers`; a `pull_request` workflow plus one on `push` to `main` (or one reusing it through `workflow_call` from a `push: branches: [main]` workflow) → none. YAML's `on` key parses as `True`: handle both.
  - `uses: actions/checkout@main` → `actions-pinned` naming the file; `@v4`, `@v4.2.1`, `@<40 hex>`, `./.github/actions/x`, `docker://alpine:3` → none.
  - a workflow without top-level `permissions` where some job lacks `permissions` → `permissions`.
  - a workflow without top-level `concurrency` → `concurrency`.
  - an unparseable YAML file → one finding `workflow-unreadable` naming the file, and the other checks skip it.
- [ ] **Step 3: Run, expect FAIL.** **Step 4: Implement.** **Step 5: Run, expect PASS.**
- [ ] **Step 6: Commit** — `feat: model a repository snapshot and check its workflows`.

---

### Task 3: Dependabot coverage and required checks

**Files:**
- Create: `src/steward/standards/dependabot_config.py`, `src/steward/standards/protection.py`
- Test: `tests/standards/test_dependabot_config.py`, `tests/standards/test_protection.py`

**Interfaces:**
- Produces: `detected_ecosystems(paths: frozenset[str]) -> frozenset[str]`, `check_dependabot(snapshot) -> list[Finding]` (`dependabot`), `check_required_checks(snapshot) -> list[Finding]` (`required-checks`).
- Manifest → ecosystem, by file name anywhere except under `node_modules/`, `vendor/`, `.venv/`, `python_modules/`: `package.json`→`npm`; `pyproject.toml`, `requirements*.txt`, `uv.lock`→`pip` (satisfied by `pip` **or** `uv`); `Cargo.toml`→`cargo`; `go.mod`→`gomod`; `*.csproj`, `*.sln`→`nuget`; `pom.xml`→`maven`; `build.gradle`, `build.gradle.kts`→`gradle`; `composer.json`→`composer`; `Gemfile`→`bundler`; `Dockerfile`→`docker`; `docker-compose.yml`, `compose.yml`, `compose.yaml`→`docker-compose`; `*.tf`→`terraform`; any `.github/workflows/*`→`github-actions`.

- [ ] **Step 1: Failing tests** — no `dependabot.yml` → finding; present without `github-actions` while workflows exist → finding naming it; `uv` entry satisfies a `pyproject.toml`; a `package.json` under `node_modules/` is ignored; empty `required_checks` → `required-checks`.
- [ ] **Step 2–4: FAIL, implement, PASS.**
- [ ] **Step 5: Commit** — `feat: check Dependabot coverage and required status checks`.

---

### Task 4: Flow, identity and AI-trace checks

**Files:**
- Create: `src/steward/standards/flow.py`, `src/steward/standards/ai_trace.py`
- Test: `tests/standards/test_flow.py`, `tests/standards/test_ai_trace.py`

**Interfaces:**
- Produces: `check_no_direct_push(snapshot)` (`direct-push`), `check_prs_reference_issues(snapshot, trusted_bots: frozenset[str])` (`pr-issue`), `check_commit_identity(snapshot, owner_email: str)` (`commit-identity`), `check_no_ai_trace(snapshot)` (`ai-trace`). `is_bot(login: str | None, email: str) -> bool` (login ends with `[bot]`, or email ends with `[bot]@users.noreply.github.com`).

- [ ] **Step 1: Failing tests** (Review Focus 1–4):
  - a commit with `from_merged_pr=False` → `direct-push` with its short SHA; `from_merged_pr=True` (a feature-branch commit brought in by a merge commit) → none; `is_root=True` → none.
  - a merged PR with `references_issue=False` by `Isma-L154` → `pr-issue` with `#N`; the same by `dependabot`, `dependabot[bot]`, `app-steward` or `app-steward[bot]` → none.
  - a human commit with another email → `commit-identity`; a bot commit (`49699333+dependabot[bot]@users.noreply.github.com`) → none.
  - `Co-authored-by:` trailer naming an AI assistant, a "Generated with …" line naming one, a PR body with either, or a branch starting `claude/`, `codex/`, `copilot/`, `cursor/`, `gemini/`, `openai/` or `ai/` → `ai-trace`, and the finding's detail contains none of those names; a commit message "Use the OpenAI API for replies" → none.
- [ ] **Step 2–4: FAIL, implement, PASS.**
- [ ] **Step 5: Commit** — `feat: check direct pushes, issue references, commit identity and AI traces`.

---

### Task 5: README and AGENTS.md checks

**Files:**
- Create: `src/steward/standards/docs.py`
- Test: `tests/standards/test_docs.py`

**Interfaces:**
- Produces: `check_readme(snapshot)` (`readme`), `check_agents(snapshot)` (`agents`).
- README standard (from the docs-sync skill): an `<img` whose `src` contains `docs/brand/banner`; at least one badge (`img.shields.io` or `/badge.svg`); a ```` ```mermaid ```` block; H2 sections `What it does`, `How it works` and `License` present; known H2 sections that are present appear in the order `What it does`, `How it works`, `Running locally` | `Installation` | `Usage`, `Deployment`, `Security`, `License`. Each missing piece is one line of the same finding.
- AGENTS.md: a heading containing `Baseline security controls`, followed by items numbered 1 to 7 each containing `implemented` or `N/A` (case-insensitive).

- [ ] **Step 1: Failing tests** — Steward's own README and AGENTS.md (read from the repository root in the test) pass; no README → finding; README without mermaid → finding mentioning the diagram; `License` before `Security` → order finding; AGENTS.md with item 6 missing → finding.
- [ ] **Step 2–4: FAIL, implement, PASS.**
- [ ] **Step 5: Commit** — `feat: check the README standard and the AGENTS.md security baseline`.

---

### Task 6: Rule registry and the issue body

**Files:**
- Create: `src/steward/standards/rules.py`, `src/steward/standards/report.py`
- Test: `tests/standards/test_rules.py`, `tests/standards/test_report.py`

**Interfaces:**
- Produces: `RULES: tuple[Rule, ...]` with `Rule(id: str, title: str)` in display order; `run_checks(snapshot, owner_email: str, trusted_bots: frozenset[str]) -> list[Finding]` (every check above, in `RULES` order). `ISSUE_TITLE = "Repository standards"`, `ISSUE_LABEL = "standards"`, `render_body(repo: RepoRef, findings: Sequence[Finding]) -> str` (a checklist grouped by rule title, `- [ ] detail`; links as `https://github.com/<repo>/commit/<sha>` and `…/pull/<n>`; an "all rules pass" body when empty).

- [ ] **Step 1: Failing tests** — `run_checks` on the compliant builder → `[]`; on a snapshot failing two rules → findings in `RULES` order; `render_body` output contains every rule title once, no `@`, and (Review Focus 5) a workflow file named `` a`b@c\n.yml `` appears as `` `ab c.yml` `` or equivalent inert text; the empty body says all rules pass.
- [ ] **Step 2–4: FAIL, implement, PASS.**
- [ ] **Step 5: Commit** — `feat: register the rules and render the tracking issue`.

---

### Task 7: GitHub transport and the standards client

**Files:**
- Create: `src/steward/github/api.py`, `src/steward/github/standards_client.py`
- Modify: `src/steward/github/client.py` (uses `GitHubApi`), `src/steward/worker/merge_queue.py`
- Test: `tests/github/test_api.py`, `tests/github/test_standards_client.py`, `tests/github/test_client.py` (fixture only)

**Interfaces:**
- Produces: `GitHubApi(http, tokens, installation_id)` with `call(method, path, body=None, accept=frozenset({200})) -> tuple[int, Any]` (the former `GitHubClient._call`) and `graphql(query: str, variables: Mapping[str, Any]) -> Any` (POST `/graphql`; a response with `errors` raises `GitHubError(200, "/graphql")`). `GitHubClient(api: GitHubApi)`. `TrackingIssue(number: int, state: str, body: str)`. `StandardsClient(api: GitHubApi, dependabot: GitHubClient)` with:

```python
async def snapshot(self, repo: RepoRef, since: datetime) -> RepoSnapshot: ...
async def tracking_issue(self, repo: RepoRef, creator: str) -> TrackingIssue | None: ...
async def create_issue(self, repo: RepoRef, title: str, body: str, label: str) -> None: ...
async def update_issue(self, repo: RepoRef, number: int, body: str, state: str) -> None: ...
```

`snapshot` = one GraphQL query (default branch name and its history since `since` with `oid`, `message`, `parents.totalCount`, `author { email user { login } }`, `associatedPullRequests(first: 5) { nodes { merged } }`; `HEAD:README.md`, `HEAD:AGENTS.md`, `HEAD:.github/dependabot.yml` blobs; the `HEAD:.github/workflows` tree with blob texts; the last 50 merged PRs with `number title body headRefName baseRefName mergedAt author { login } closingIssuesReferences { totalCount }`, filtered to the default branch and the window) + `GET /git/trees/<branch>?recursive=1` + `dependabot.required_checks()`. `tracking_issue` = `GET /issues?state=all&labels=standards&creator=<creator>`. `update_issue` sends `state_reason: "completed"` when closing.

- [ ] **Step 1: Failing tests** against `FakeHttp` (extend it to route `POST /graphql` by a marker in the query): GraphQL `errors` → `GitHubError`; a canned GraphQL response maps to the expected `RepoSnapshot` (bot author with `user: null` keeps `author_login=None`; a merged PR into another base is dropped); the tree's paths land in `paths`; missing README blob → `readme=None`; `tracking_issue` returns the first match or `None`; `update_issue(..., state="closed")` sends `state_reason`.
- [ ] **Step 2: Refactor** `GitHubClient` onto `GitHubApi`; the existing client tests pass unchanged except their fixture.
- [ ] **Step 3–5: FAIL, implement, PASS.** **Step 6: Commit** — `feat: add a shared GitHub transport with GraphQL and a standards client`.

---

### Task 8: The standards service

**Files:**
- Create: `src/steward/standards/ports.py`, `src/steward/standards/service.py`
- Test: `tests/standards/fakes.py`, `tests/standards/test_service.py`

**Interfaces:**
- Produces: `StandardsGitHub` Protocol (the four `StandardsClient` methods). `StandardsService(github: StandardsGitHub, owner_email: str, own_login: str, clock: Callable[[], datetime])` with `async audit(repo: RepoRef) -> list[Finding]`. Trusted bots: `dependabot`, `dependabot[bot]`, `own_login`, `own_login` without `[bot]`.

- [ ] **Step 1: Failing tests** — failing repo, no issue → created with title, body, label; failing, open issue with the same body → no write; failing, open with another body → updated, state open; failing, closed issue → reopened with the new body; passing, open issue → updated to the "all rules pass" body and closed; passing, no issue → no write; `snapshot` asked for `since = clock() - 30 days`.
- [ ] **Step 2–4: FAIL, implement, PASS.** **Step 5: Commit** — `feat: keep one tracking issue per repository`.

---

### Task 9: The weekly sweep

**Files:**
- Create: `src/steward/standards/sweep.py`
- Modify: `src/steward/github/app_auth.py`
- Test: `tests/standards/test_sweep.py`, `tests/github/test_app_auth.py`

**Interfaces:**
- Produces: `async installation_ids(http, app_id, signer, now) -> list[int]` (`GET /app/installations`, JWT). `InstalledRepo(repo: RepoRef, archived: bool, topics: tuple[str, ...])`; `StandardsClient.installed_repositories() -> list[InstalledRepo]` (`GET /installation/repositories?per_page=100`). `async sweep(installations: Sequence[int], repositories: Callable[[int], Awaitable[Sequence[InstalledRepo]]], audit: Callable[[int, RepoRef], Awaitable[None]]) -> int` (audits every managed repository, one at a time; an exception from one audit is printed and does not stop the others; returns how many were audited).

- [ ] **Step 1: Failing tests** — two installations, five repositories of which one archived and one `steward-ignore` → three audits; an audit raising `GitHubError` → the rest still run; `installation_ids` maps the JWT call.
- [ ] **Step 2–4: FAIL, implement, PASS.** **Step 5: Commit** — `feat: sweep every managed repository`.

---

### Task 10: Worker wiring

**Files:**
- Create: `src/steward/worker/standards_audit.py`
- Modify: `src/steward/worker/entry.py`, `src/entry.py`, `src/steward/config.py`, `wrangler.toml`, `pyproject.toml` (mypy override for the new adapter)
- Test: `tests/test_config.py`, `tests/integration/test_webhook.py`, `tests/fixtures/push_main.json`

**Interfaces:**
- Produces: `Config.owner_email: str` (required `OWNER_EMAIL`). `StandardsAudit(DurableObject)` answering `POST /audit` with `{"installation_id", "owner", "name"}` → `{"findings": <count>}`, holding its own `InstallationTokens` and cached bot login like `MergeQueue`. `Default.scheduled(controller, env, ctx)` running `sweep` with one `StandardsAudit` call per repository. `wrangler.toml`: `[vars] OWNER_EMAIL`, `[triggers] crons = ["0 6 * * 1"]`, binding `STANDARDS_AUDIT` → `StandardsAudit`, migration `v2` with `new_sqlite_classes = ["StandardsAudit"]`.

- [ ] **Step 1: Failing tests** — `load_config` without `OWNER_EMAIL` → `MissingConfig("OWNER_EMAIL")`; integration: a signed push to `main` answers 202 `{"queued": 1}`, to another branch `{"queued": 0}`; a signed `workflow_run` from a `steward-ignore` repository → `{"queued": 0}`; with the dev server started with `--test-scheduled`, a request to the scheduled-test route given in the Cron Triggers docs, with `cron=0 6 * * 1`, answers 200 and the log shows the sweep ran.
- [ ] **Step 2–4: FAIL, implement, PASS** (all checks, dry-run bundle, integration against the dev server).
- [ ] **Step 5: Commit** — `feat: audit on pushes to main and in a weekly sweep`.

---

### Task 11: Docs, review, merge and go live

- [ ] **Step 1:** README (What it does, How it works with the audit path in the diagram, Deployment: the App needs the **Push** event and `OWNER_EMAIL`), `AGENTS.md` architecture lines; `docs-sync` and `security-scan` skills.
- [ ] **Step 2:** Self-review of the whole branch against the spec and this plan's Review Focus (no subagent); fix Critical/Important findings with a failing test first.
- [ ] **Step 3:** PR `Closes #13`, green CI, **merge commit**, deploy, `/health` 200 with the merged commit.
- [ ] **Step 4 (owner, guided):** App settings → Permissions & events → subscribe to **Push**; accept the change on the installation if GitHub asks.
- [ ] **Step 5:** Add the topic `steward-ignore` to Steward, Isma-L154, RodeCustoms-Ecommerce, AcademiaANP, OpenAI-Chatbot-through-WhatsApp and YoutubeAPI_Middleware (`gh repo edit <repo> --add-topic steward-ignore`).
- [ ] **Step 6: Verify live** — a push to `main` of one managed repository produces or updates its "Repository standards" issue (read it: no `@`, no AI assistant names, findings make sense); trigger the cron once from the dashboard ("Trigger" on the Worker's cron) or wait for Monday, and check that every managed repository was audited and no ignored one was touched.
