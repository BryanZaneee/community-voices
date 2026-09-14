# Contributing

## Branch Strategy

One long-lived branch: `main`. Always deployable. All work happens on
short-lived branches cut from `main` and merged back via PR.

```
feature/* ──▶ main
```

Target under 2 days from branch cut to merge. Anything unfinished at that point
ships behind a feature flag rather than sitting on a branch — see
[Long-Running Work](#long-running-work) below.

## Branch Naming

`<prefix>/<kebab-case-description>`, under ~40 characters.

| Prefix | Use for | Example |
| --- | --- | --- |
| `feature/` | New functionality | `feature/oauth-login` |
| `fix/` | Bug fixes | `fix/token-refresh-race` |
| `refactor/` | Non-behavioral code changes | `refactor/extract-db-client` |
| `chore/` | Tooling, deps, CI, config | `chore/bump-node-22` |
| `docs/` | Documentation only | `docs/api-auth-flow` |
| `test/` | Test-only changes | `test/cover-billing-webhook` |

## Workflow

1. `git checkout main && git pull origin main`
2. `git checkout -b feature/your-thing`
3. Commit in small, logical units (see [Commits](#commits))
4. `git push -u origin feature/your-thing`
5. Open a PR into `main` using the PR template
6. CI green + reviewed, then squash merge
7. Branch auto-deletes

## Long-Running Work

Don't hold a branch open for weeks. Merge incomplete work behind a feature flag
or an unrouted module so it integrates continuously and ships dark. Moving the
"not ready" boundary from git into runtime config makes it testable in
production and reversible in seconds.

## Releases

Tag `main` when you ship something users pin to:

```bash
git tag -a v1.2.0 -m "v1.2.0" && git push origin v1.2.0
```

SemVer: breaking → MAJOR, feat → MINOR, fix → PATCH. Conventional Commits make
this derivable automatically (see [Automation](#automation)).

For a release that needs stabilization time, cut a short-lived
`release/v1.2.0` branch from `main`, fix only on it, tag, then merge it back.
Delete it after.

## Hotfixes

Same as any fix: branch from `main`, PR into `main`, tag. No special path.

## Variant: adding a develop branch

Skip this section unless the repo needs it. A permanent integration branch costs
a second merge, a back-merge after every hotfix, and a subjective "is it ready?"
call. Industry practice has moved away from it — Atlassian now documents Gitflow
as legacy, and DORA data associates long-lived branches with lower deploy
frequency and higher change failure rates.

Adopt `develop` only when both are true:

- There's a real staging environment that deploys from a branch other than prod
- Releases are versioned and consumed by someone other than you

If so:

- `feature/*` → `develop` → `main`. `develop` is the default branch so PRs
  target it.
- `develop` → `main` on a fixed cadence (weekly, or per milestone), not when it
  "feels ready". Title the PR `release: v<version>`, merge with a merge commit
  to preserve the boundary, then tag.
- Hotfixes branch from `main`, PR into `main`, tag, then **immediately merge
  `main` back into `develop`**. Skipping the back-merge is how this model
  breaks: the fix silently disappears on the next release.
- Protect both branches identically.

## Commits

Conventional Commits wrapped to the 50/72 rule:

```
<type>(<scope>): <subject, max 50 chars>
                                            ← blank line, required
Body explaining WHY the change was made,    ← wrapped at 72 chars
not what changed. The diff shows what.
                                            ← blank line
Closes #42
```

Git truncates long subjects in `--oneline` and most UIs; 72 in the body accounts
for git's log indent inside an 80-column terminal. Linux kernel convention, de
facto standard.

Types: `feat` `fix` `refactor` `chore` `docs` `test` `perf` `build` `ci`

- Imperative mood ("add", not "added"), no trailing period
- Blank line between subject and body — git parses on it
- Body only when the change needs explaining
- Breaking: `!` after the type (`feat(api)!: drop v1 endpoints`) plus a
  `BREAKING CHANGE:` footer
- Footer references: `Closes #42`, `Refs #17`

Example:

```
fix(auth): handle null org on session lookup

Sessions created before the org migration have a null orgId, which
crashed the dashboard loader on first render. Fall back to the
personal workspace instead of throwing.

Closes #218
```

Set the template so the shape is pre-filled:
`git config commit.template .gitmessage`

## Pull Requests

- Fill every section of `.github/pull_request_template.md`; N/A only when a
  section genuinely doesn't apply
- Title uses the same Conventional Commits format, ≤ 50 chars — it becomes the
  squash commit subject
- Keep the diff under ~400 lines; split if larger
- Draft until CI is green and the description is complete
- Self-review the diff before requesting review
- Rebase if behind: `git fetch origin && git rebase origin/main`
- Squash merge into `main`. Never rebase-merge a shared branch
- On solo repos, still open the PR — the CI gate and the written description are
  the point

## Branch Protection

On `main` (and `develop` if used):

- Require a PR before merging; no direct pushes, admins included
- Require status checks: lint, typecheck, test, build
- Require branches up to date before merging
- Require conversation resolution
- Auto-delete head branches after merge
- Restrict force pushes and branch deletion

Add `CODEOWNERS` once more than one person contributes.

## Automation

Written rules are probabilistic; hooks are not.

| Concern | Tool |
| --- | --- |
| Commit message shape | commitlint + husky `commit-msg` hook |
| Lint/format on stage | lint-staged + husky `pre-commit` |
| Version + changelog | release-please or changesets |
| CI gates | GitHub Actions on `pull_request` |

`commitlint.config.js` enforcing Conventional Commits and 50/72:

```js
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "header-max-length": [2, "always", 50],
    "body-max-line-length": [2, "always", 72],
  },
};
```

## Code Standards

- Lint, format, and typecheck pass locally before pushing
- Tests added or updated for any behavioral change
- No commented-out code, stray debug logs, or TODO without a linked issue
- Env vars in `.env.example` with a comment; never real values in the repo
- Justify new dependencies in the PR description

## This repository

Tests, from the repo root (no API keys needed):

```bash
cd backend && .venv/bin/python -m pytest tests -q
```

First-time setup of that venv:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Never commit:

- `.env` (the repo root copy; `.env.example` is the tracked one)
- a regenerated `data/community.sqlite`, unless changing the committed corpus
  is the point of the PR. It is a binary and re-ingesting rewrites it wholesale
- `frontend/dist/` churn unrelated to a frontend change. Rebuild it with
  `npm run build` only when `frontend/src/` actually changed
