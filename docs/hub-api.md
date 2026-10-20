# Hub API

The read-only API Steward serves to the hub (`hub.cloudils.com`). It exists only on the `HubApi` entrypoint, which only a service binding can reach: `steward.cloudils.com` answers 404 for these paths. Design: [`docs/superpowers/specs/2026-10-19-hub-api-design.md`](superpowers/specs/2026-10-19-hub-api-design.md).

## Binding

In the hub's `wrangler.jsonc`:

```jsonc
"services": [
  { "binding": "STEWARD", "service": "steward", "entrypoint": "HubApi", "props": { "caller": "hub" } }
]
```

Call it with `env.STEWARD.fetch("https://steward/v1/health")` or `.../v1/report`. The hostname is a placeholder.

Steward accepts a request only when all of these hold:
- `props.caller` is exactly `"hub"`;
- the method is `GET`;
- the path is exactly one of the two below;
- there is no query string and no body.

## `GET /v1/health`

Health of every repository Steward manages, read from GitHub at most once every 5 minutes.

```json
{
  "generated_at": "2026-10-19T12:00:00Z",
  "repositories": [
    {
      "repo": "Isma-L154/nextsode",
      "url": "https://github.com/Isma-L154/nextsode",
      "ci": "passing",
      "deploy": { "state": "succeeded", "at": "2026-10-18T21:04:11Z" },
      "last_commit_at": "2026-10-18T20:59:02Z",
      "pull_requests": { "open": 3, "dependabot": 2 },
      "issues": { "open": 1 },
      "security_alerts": { "critical": 0, "high": 1, "medium": 0, "low": 0 },
      "standards": { "state": "failing", "url": "https://github.com/Isma-L154/nextsode/issues/7", "findings": 4 }
    }
  ]
}
```

| Field | Values | When unknown |
|---|---|---|
| `repo` | `owner/name`; repositories are sorted by it | never |
| `url` | the repository on GitHub | never |
| `ci` | `passing`, `failing`, `running`, `unknown`: combined checks of `main`'s head commit | `unknown` |
| `deploy.state` | `succeeded`, `failed`, `running`, `unknown`: latest deployment to the `production` environment | `unknown` (also when the repository has no `production` deployments) |
| `deploy.at` | when that deployment was created | `null` |
| `last_commit_at` | the head commit of the default branch | `null` |
| `pull_requests.open` | open pull requests | the whole object is `null` |
| `pull_requests.dependabot` | those opened by Dependabot | `null` (more than 100 open, so not counted) |
| `issues.open` | open issues, the standards issue included | the whole object is `null` |
| `security_alerts` | open Dependabot alerts by severity | the whole object is `null` |
| `standards.state` | `failing` (Steward's standards issue is open), `passing`, `unknown` | `unknown` |
| `standards.url`, `standards.findings` | the issue and its unchecked items, only when `failing` | `null` |

All times are ISO 8601 UTC with `Z`.

## `GET /v1/report`

The weekly report of pending work, built every Monday after the 06:00 UTC sweep (and once on the first request if none exists yet). A failed build keeps the previous report, so `generated_at` always says how old it is.

```json
{
  "generated_at": "2026-10-19T06:03:12Z",
  "major_ready":     [{ "repo": "Isma-L154/hub", "number": 12, "title": "Bump wrangler from 4.x to 5.0", "url": "https://github.com/Isma-L154/hub/pull/12" }],
  "major_failing":   [],
  "updates_failing": [],
  "updates_blocked": [],
  "standards":       [{ "repo": "Isma-L154/nextsode", "url": "https://github.com/Isma-L154/nextsode/issues/7", "findings": 4 }],
  "unknown":         []
}
```

- **`major_ready`, `major_failing`, `updates_failing`, `updates_blocked`:** open Dependabot pull requests labelled `major-ready`, `major-broken`, `update-broken` and `update-blocked`. Pull requests by anyone else never appear.
- **`standards`:** repositories whose standards issue, opened by Steward, is open.
- **`unknown`:** repositories whose pull requests or standards issue could not be read. They have no items in the other lists.

Items are sorted by `repo`, then `number`.

## Errors

Every error body is exactly `{"error": "<code>"}`.

| Status | Code | Meaning |
|---|---|---|
| 400 | `invalid_request` | a query string or a body was sent |
| 403 | `forbidden` | the binding does not carry `props.caller == "hub"` |
| 404 | `not_found` | another path |
| 405 | `method_not_allowed` | not `GET` |
| 429 | `rate_limited` | more than 60 calls in a minute |
| 500 | `misconfigured` | Steward is missing a secret |
| 502 | `github_unavailable` | GitHub could not be read, or Steward failed while answering; nothing stale is served |

## What the hub must do

- Treat any status other than 200, and any body that fails its own validation, as unknown.
- Render every string with `textContent`, never as HTML. Titles are plain text: Steward strips control and bidirectional characters and caps them at 200 characters, but does not escape markup.
- Link only to the `url` values given. Every one matches `^https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+(/(pull|issues)/[0-9]+)?$`.
