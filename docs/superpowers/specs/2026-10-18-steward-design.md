# Steward — design

A GitHub App for the owner's own repositories: it merges safe Dependabot updates, checks every repository against the owner's engineering rules, and is the single source of GitHub data for the hub (`hub.cloudils.com`).

Calls marked **(builder's call, settled)** were made while writing this design, not by the owner. They can be changed without revisiting the rest.

## Intent

The owner (GitHub account `Isma-L154`) maintains around twenty repositories that all follow the same global rules: CI/CD with GitHub Actions, Dependabot, a standard README, an `AGENTS.md` with a security baseline, an issue → branch → pull request flow, a fixed commit identity and no AI trace anywhere on GitHub.

Two things cost time today:

1. **Dependabot pull requests pile up** across several repositories. Clearing them means visiting each repository and merging one by one, or asking an assistant to review them all.
2. **Rule drift is only caught by hand.** A repository missing pinned actions, `permissions:`, Dependabot or a README section is noticed only when someone happens to look.

Steward removes the routine part of both and reports the rest in one place, the hub.

## Goals

1. **Dependabot:** patch and minor updates whose CI passes are approved and merged without the owner. Major updates are never merged automatically; they are labelled by CI result and wait for the owner.
2. **Standards:** every repository where the App is installed is checked against the mechanical rules below. Each repository has at most one tracking issue listing what fails, updated in place and closed when everything passes.
3. **Hub data:** the App serves live per-repository health and a weekly report of pending work to the hub, through a Cloudflare service binding only. The hub holds no GitHub credential (see Isma-L154/hub#11).

## Non-goals

- An AI summary of breaking changes for major updates. With tests and build passing the owner has what they said they need; it can be added later. **(builder's call, settled)**
- Pull requests that fix rule violations. The App reports; it does not change repository content.
- Checking rules a machine cannot judge reliably: SOLID, comment quality, code written in English, whether a security control is actually implemented (only that it is declared).
- Acting on repositories from the hub, or notifications outside the hub (Discord, email).
- A public Marketplace listing or installation on other accounts.

## Anti-goals

These would make it a failure even if everything else works:

- A major update merged without the owner.
- Anything merged whose CI did not pass, or merged in a repository where `main` has no required status checks. Without required checks there is nothing to trust, so the App fails closed and does not auto-merge there.
- Two Dependabot updates merged into a combination that CI never tested.
- Issue noise: a new issue on every run, or an issue body that pings people.
- Private repository data reachable from the public internet.
- The App itself leaving an AI trace: its issue bodies, labels and comments must not name any AI assistant, even when reporting such a trace in a repository (say "commit `abc1234` carries an AI attribution trace", never quote the term).

## Constraints

- **Language and runtime:** Python on Cloudflare Workers (owner's choice), managed with `uv` and `pywrangler`, dependencies in `pyproject.toml`. Python Workers accept pure PyPI packages and those bundled with Pyodide (including `cryptography` and `PyYAML`). Cron triggers are supported.
- **Cost:** Cloudflare free tier, like the owner's other Workers projects. **(builder's call, settled)**
- **Global rules apply to this repository itself:** code, comments, commits and issues in English; issue → branch → PR, never pushing to `main`; commits authored with `ismaleonsaenz@gmail.com`; no AI trace in commits, PRs, issues or branch names; SOLID; minimal comments; CI/CD from the first PR; README following the docs-sync standard; the seven security controls decided in `AGENTS.md`.
- **Manual setup by the owner:** registering the GitHub App in the account settings, generating its private key, setting the webhook URL and secret, and choosing which repositories to install it on. The App checks exactly the repositories it is installed on, so repositories that should not be checked (the profile repository, for example) are simply left out at install time.

## Design

### The App

- **Permissions (least privilege):** Metadata read; Contents read and write (needed to merge); Pull requests read and write (approve, label, merge); Issues read and write (tracking issue, labels); Checks read; Actions read (workflow runs); Administration read (branch protection). Nothing else.
- **Webhook events:** `pull_request`, `check_suite`, `workflow_run`, `push`.
- **Webhook authentication:** every delivery's `X-Hub-Signature-256` is verified with HMAC-SHA256 and a constant-time comparison before the body is parsed. Unsigned or wrongly signed requests get 401.
- **GitHub authentication:** an RS256 App JWT signed with the private key, exchanged for a short-lived installation token, cached until shortly before it expires.
- **Public surface:** the webhook route only. Everything the hub reads goes through the service binding and is not routable from the internet.

### Dependabot module

1. Re-evaluate a pull request authored by `dependabot[bot]` when its checks complete or it is opened or updated.
2. Classify the update as patch, minor or major from the version change Dependabot reports. A grouped update counts as major if any member is major.
3. **Patch or minor**, all required checks successful, mergeable, and checks run against the current `main` → approve and merge. Use squash when the repository allows it, otherwise the repository's allowed method. **(builder's call, settled)**
4. **Patch or minor with failing CI** → label `update-broken` and leave it.
5. **Major with all checks successful** → label `major-ready`. **Major with failing checks** → label `major-broken`. Never approve or merge either.
6. **One merge at a time per repository.** After one update merges, Dependabot rebases the others; each is re-evaluated when its checks complete again. The builder chooses the mechanism that guarantees a PR is never merged on checks run against an outdated `main` (a per-repository lock, refusing to merge unless the PR head is up to date with `main`, or both).
7. A repository without required status checks on `main` never gets auto-merges. It shows up as a standards failure instead.

### Standards module

**When it runs:** on every push to `main` of an installed repository (that repository only), and in a weekly sweep over all installed repositories.

**What it checks:**

| Area | Check |
|---|---|
| CI/CD | A workflow runs on `pull_request` and on `push` to `main` |
| CI/CD | Every `uses:` is pinned to a commit SHA or a major tag, never a branch |
| CI/CD | Every workflow declares `permissions:` |
| CI/CD | Every workflow declares `concurrency` |
| CI/CD | `.github/dependabot.yml` exists and covers `github-actions` plus each package ecosystem detected from the repository's manifest files |
| CI/CD | `main` is protected with at least one required status check |
| Flow | Every commit on `main` came from a merged pull request |
| Flow | Every merged pull request references an issue (`Closes`, `Fixes` or `Resolves #N`) |
| Identity | Every commit on `main` is authored with the configured email (`ismaleonsaenz@gmail.com`, set as configuration, not hard-coded) |
| No AI trace | No AI assistant named in commit messages, co-author trailers, PR titles or bodies, or branch names |
| Docs | The README has a banner image, status badges, a Mermaid diagram and the section order defined by the `docs-sync` skill in `Isma-L154/agent-skills` |
| Security | `AGENTS.md` exists and states each of the seven baseline controls as implemented or N/A with a reason |

Checks about commits and pull requests look only at activity since the previous run, and the last 30 days on a repository's first run, so old history from before the rules existed is not flagged. **(builder's call, settled)**

**Reporting:** one issue per repository titled "Repository standards", labelled `standards`, opened by the App, with one checkbox per failing rule and a link to the offending file, commit or pull request. Each run updates the same issue; when everything passes it is closed; if something breaks again it is reopened, not duplicated. Text taken from the repository (file names, PR titles) is escaped so it cannot render as a mention, link or markup in the issue.

Archived repositories are skipped.

### Data for the hub

Exposed only through the service binding, as JSON:

- **Health**, per installed repository: latest CI run result on `main`, latest deploy result and time, open pull requests (Dependabot counted apart), open issues. Read from GitHub on demand and cached for 5 minutes, so page views do not spend the GitHub rate limit. **(builder's call, settled)**
- **Weekly report**, generated by the weekly cron right after the sweep and stored with its generation time: major updates ready for review, major updates with failing CI, Dependabot PRs with failing CI, and repositories failing standards, each with a link. Only pending items, nothing that already resolved itself.
- **Schedule:** Mondays 06:00 UTC. **(builder's call, settled)**

How "latest deploy" is found per repository (a workflow named `deploy`, a job that runs `wrangler deploy`, or repositories that deploy outside Actions) is left to the builder; it should read unknown rather than guess when unclear, matching the hub.

### Security baseline

| Control | Decision |
|---|---|
| 1. Secrets | App private key, webhook secret and App ID as Worker secrets; `.dev.vars.example` with keys and no values; the Worker refuses to serve if any is missing |
| 2. CORS | N/A: no browser calls the App. The webhook comes from GitHub and the hub calls through a service binding |
| 3. Validation | Signature first; then the webhook body is validated against an allowlist of the fields used; body size capped |
| 4. Sanitize | No SQL. Repository-derived text is escaped before it goes into GitHub markdown |
| 5. Rate limiting | Rate limit on the webhook route; GitHub API calls stay within the installation's budget and back off on secondary limits |
| 6. RLS | N/A: single owner, no multi-user data |
| 7. CSP | The Worker serves no HTML; every response still carries the security headers (`nosniff`, `Referrer-Policy`, HSTS, a deny-all CSP) |

### CI/CD

GitHub Actions from the first PR: `uv` with caching, lint, type check, tests, and a build check on every PR and push to `main`; deploy from `main` with `pywrangler` only after CI passes, using a `CLOUDFLARE_API_TOKEN` repository secret in a `production` environment. Actions pinned, `permissions:` and `concurrency` on every workflow, Dependabot for Python dependencies and GitHub Actions.

Tests must prove at least: signature verification rejects bad and missing signatures; a major update is never merged in any combination of inputs (a good fit for a property-based test); no merge without required checks; tracking issue upsert is idempotent (two runs, one issue); each standards check passes and fails on fixtures.

## Order of work

1. Repository, CI/CD, `AGENTS.md`, README, App authentication and webhook verification.
2. Dependabot module.
3. Standards module and tracking issues.
4. Service binding API for the hub (health and weekly report).
5. Isma-L154/hub#11, in the hub repository.

## Left to the builder

Module layout, Python libraries within the Pyodide constraint, storage choice for cache, report and locks (KV, Durable Objects or both), the lock mechanism, the deploy-detection heuristic, the exact JSON shape of the hub API (agreed with hub#11 when it is built).
