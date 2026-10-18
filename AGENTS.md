# Steward

A GitHub App for the owner's own repositories (account `Isma-L154`). It merges Dependabot patch and minor updates once CI passes, labels major updates and failing ones for the owner, and will check every repository against the owner's engineering rules and feed the hub (`hub.cloudils.com`). It runs as a Python Worker on Cloudflare at `steward.cloudils.com`. The design is in `docs/superpowers/specs/2026-10-18-steward-design.md`.

## Stack

- **Language:** Python 3.14 (Pyodide inside workerd)
- **Framework:** none; Cloudflare Python Workers (`workers` SDK: `WorkerEntrypoint`, `DurableObject`)
- **Package manager:** uv (`uv.lock`) with `pywrangler`; npm only for `wrangler` (`package-lock.json`)
- **Database:** none; Durable Object storage holds small per-repository state (rebase requests)
- **Deployment target:** Cloudflare Workers, custom domain `steward.cloudils.com`, deployed by `.github/workflows/deploy.yml` from `main`
- **Key libraries:** `cryptography` (RS256 App JWT), `pydantic` (webhook payload validation); dev: pytest, hypothesis, httpx, ruff, mypy

## Commands

- Dev server: `uv run pywrangler dev` (needs `.dev.vars` with `APP_ID`, `PRIVATE_KEY`, `WEBHOOK_SECRET`; see `.github/actions/start-dev-server/action.yml` for a throwaway set)
- Build: `uv run pywrangler deploy --dry-run --outdir .wrangler/dry-run`
- Test (unit): `uv run pytest`
- Test (e2e): no UI; integration tests against the dev server: `uv run pytest -m integration`
- Lint / format: `uv run ruff check .` and `uv run ruff format --check .`
- Type check: `uv run mypy src tests`

## Architecture & Conventions

- `src/steward/` is a pure Python core with no Workers imports, tested on CPython: `webhooks/` (signature, payload parsing), `github/` (models, App auth, REST client), `dependabot/` (update type, CI verdict, decision table, service).
- `src/steward/worker/` holds the thin runtime adapters: `entry.py` (`Default`: `/health`, `/webhook`), `merge_queue.py` (one `MergeQueue` Durable Object per repository, serialized with an `asyncio.Lock`), `fetch_http.py`, `rebase_memory.py`. `src/entry.py` is the shim Wrangler loads.
- Services depend on small `Protocol` ports (`dependabot/ports.py`, `github/http.py`); tests use in-memory fakes (`tests/dependabot/fakes.py`, `tests/github/fake_http.py`), never network mocks.
- Decisions are pure functions over frozen dataclasses (`decide(Facts) -> Decision`); side effects live in the service.
- Anything unclear fails closed: unknown update type counts as major, a missing required check keeps CI pending, no required checks means no auto-merge.
- Never import `cryptography` at module level: it reads entropy on import, which workerd forbids at Worker startup. Import it inside the function that needs it and use `TYPE_CHECKING` for types.

---

# Engineering Workflow (Superpowers)

This project uses the `superpowers` plugin as its default engineering discipline. Follow this loop for any non-trivial change:

1. **Brainstorm** (`superpowers:brainstorming`) — before writing a new feature or component, clarify intent and requirements. Don't skip this because the ask "sounds simple."
2. **Plan** (`superpowers:writing-plans`) — for multi-step work, write the plan before touching code.
3. **Test-first** (`superpowers:test-driven-development`) — write the failing test before the implementation, for both bugfixes and features.
4. **Debug systematically** (`superpowers:systematic-debugging`) — on any bug or unexpected behavior, diagnose root cause before proposing a fix. No speculative patches.
5. **Isolate risky work** (`superpowers:using-git-worktrees`) — for exploratory or large feature work, use a worktree instead of the main working copy.
6. **Verify before claiming done** (`superpowers:verification-before-completion`) — never say "this works" without having actually run it and shown the output. Evidence before assertions.
7. **Request review** (`superpowers:requesting-code-review` / `receiving-code-review`) — before merging, run a review pass and actually engage with the feedback (not blind acceptance, not dismissal).
8. **Close out** (`superpowers:finishing-a-development-branch`) — once tests are green and reviewed, decide how to integrate (merge, PR, rebase) explicitly rather than leaving branches dangling.

---

# Model Selection

Don't run everything on one model. Pick per task:

| Task type | Model | Why |
|---|---|---|
| Architecture, complex refactors, multi-file feature work, hardest debugging | **Opus 5** (`opus`) | Current flagship for agentic coding — strongest on difficult, long-horizon work. Default for this project. |
| The genuinely hardest problem in the codebase (rare) | **Fable 5** (`fable`) | Anthropic's most capable model, ~2x Opus 5 cost. Reserve for problems Opus 5 actually struggles with — not a default upgrade. |
| Routine day-to-day coding, well-specified implementation, most PR work | **Sonnet 5** (`sonnet`) | Near-Opus quality at ~40% of the cost. Best default for high-volume, everyday coding. |
| Narrow mechanical work (bulk greps, simple classification, boilerplate, repetitive edits) | **Haiku 4.5** (`haiku`) | Fastest and cheapest — fine for well-scoped work where the intelligence ceiling doesn't matter. |

**How to pin a model in Claude Code:**

| Mechanism | Scope | Example |
|---|---|---|
| `/model` | Current interactive session | `/model sonnet` |
| `--model` CLI flag | One session at launch | `claude --model opus` |
| `model` in `settings.json` | Persistent default (user or project scope) | `{"model": "opus"}` |

Switch with `/model` when the task type changes, rather than staying on one model for a whole session out of inertia.

## Required: annotate every plan with a model recommendation

**Whenever you produce a plan, task breakdown, or list of next steps for this project** (via `writing-plans`, `brainstorming`, or just answering "what's left to do") — **tag each task with a recommended model and a one-line reason**, using the table above as the criteria. Don't wait to be asked for this; it's a default part of how a plan is presented here.

Format each task like:

```
1. Refactor the auth module to support OAuth — [Opus 5: multi-file, security-sensitive, needs judgment]
2. Add unit tests for the new endpoints — [Sonnet 5: well-specified, routine]
3. Update 40 files to the new import path — [Haiku 4.5: mechanical, no judgment needed]
```

If a task doesn't clearly need a specific model, say so ("any model is fine here") rather than defaulting to Opus for everything — the point is to actually differentiate, not to rubber-stamp the default.

---

# Security

Security tooling is mandatory for this project, not optional nice-to-have. Apply these at the stages noted:

| Skill | When to run it |
|---|---|
| `semgrep` | Continuously while coding — real-time SAST feedback on every meaningful change. |
| `static-analysis` (CodeQL + Semgrep + SARIF) | Before opening a PR and before any release/deploy — full scan. |
| `differential-review` | On every PR / before merging any feature branch — diff-focused review with blast-radius estimation. |
| `insecure-defaults` | Whenever touching config, env var handling, auth defaults, or anything with a fallback value. |
| `sharp-edges` | When designing or reviewing any public API, config schema, or shared utility — check for footguns and unsafe defaults. |
| `supply-chain-risk-auditor` | Whenever a new dependency is added or an existing one is upgraded. |
| `semgrep-rule-creator` | When a bug pattern shows up more than once — turn it into a reusable rule instead of relying on memory. |
| `second-opinion` | For security-sensitive or high-risk changes (auth, payments, data access) — get an independent LLM review before merging. |
| `security-scan` | After any change to an exposed surface, and before every release — runs the scanners and verifies the baseline controls with evidence. |
| `threat-model` | Before building auth, payments, personal-data or upload features — STRIDE on the design, with a verification test per mitigation. |

**Non-negotiables:**
- Never hardcode secrets, API keys, or credentials. Everything sensitive goes through env vars (`.env`, never committed).
- Any new auth/crypto/payment code path requires a `differential-review` pass before merge, no exceptions.

## Baseline security controls

The seven controls are defined in global rule 10. In this project:

1. **Secrets in environment variables — implemented.** `APP_ID`, `PRIVATE_KEY` and `WEBHOOK_SECRET` are Worker secrets; `.dev.vars.example` lists the keys without values; any missing or unparseable one makes every route, `/health` included, answer 500.
2. **CORS — N/A.** No browser ever calls this Worker: the only callers are GitHub's webhook deliveries and, later, the hub through a service binding. No CORS headers are sent.
3. **Backend validation — implemented.** The webhook signature is checked first; then the body is validated by strict pydantic models that declare only the fields used (no coercion); bodies over 1 MiB or without a declared length are rejected with 413.
4. **Sanitize before storage — implemented.** No SQL and no file paths from input; Durable Object keys are built from integers and commit SHAs. Text derived from repositories is escaped before it goes into GitHub markdown (standards module).
5. **Rate limiting — implemented.** The `WEBHOOK_LIMIT` binding allows 120 webhook requests per minute per client IP; GitHub API errors are not retried in a loop (the next webhook re-evaluates).
6. **Row Level Security — N/A.** Single owner, no multi-user data and no database.
7. **Content Security Policy — implemented.** No HTML is served; every response carries `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'`, HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.

---

# QA & Testing

| Skill | Use for |
|---|---|
| `code-review` / `simplify` | Every PR — correctness bugs, coverage gaps, silent failures, stale comments, unnecessary complexity. |
| `playwright` | Browser-based E2E testing — real user flows, forms, navigation, visual regressions. |
| `property-based-testing` | Anywhere there's parsing, serialization, or validation logic — prefer property tests over example-only tests. |
| `mutation-testing` | Periodically on critical modules, to check whether the existing test suite actually catches regressions (not just covers lines). |
| `testing-handbook-skills` | If/when this project needs fuzzing (parsers, binary formats, untrusted input) — pick the right fuzzer per language from this skill set. |

QA gate before merge: `code-review` + `differential-review` + (playwright e2e if the change touches user-facing flows).

---

# UI/UX

- Use `ui-ux-pro-max` for anything touching layout, components, color, typography, or design system decisions. Don't invent styling ad hoc — check it against the skill's guidance first (styles, palettes, accessibility, responsive patterns).

---

# Git & Commit Discipline

- Never commit directly to `main`. Every change starts with an issue, happens on a `feature/*` branch, and ends with a PR that says `Closes #N`.
- Stop at logical checkpoints and propose a commit with a clear semantic message — don't let changes pile up uncommitted.
- Before merging: tests green, `differential-review` clean (or findings triaged), `code-review` run.

---

# Notes for Claude

- **Single session, no subagents.** All work happens in the one interactive session. Never dispatch subagents, parallel agents, background agents or worktree-isolated agents, and do not suggest them — including for work that looks parallelizable. If a task is large, sequence it or split it, in this session.
- All the skills referenced above are installed globally (`user` scope) — they're available in this project automatically, no per-project setup needed.
- Don't force a skill that doesn't fit the task just because it's listed here — this file sets *default* discipline and *when* to reach for each tool, not a mandatory checklist for every single change.
- Project-specific overrides always win over the general defaults above — if a section below contradicts something above, follow the section below.

- `cryptography`, `cffi`, `pydantic` and `pydantic-core` are pinned to the versions on the Pyodide index the Workers runtime uses; they are excluded from the uv cooldown and from Dependabot. Bump them only together with the runtime, and confirm with `uv run pywrangler sync`.
- The App must never leave an AI trace: its comments, labels and issue bodies never name an AI assistant.
