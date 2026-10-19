# Canonical Workflow — operational notes

Last updated: 2026-10-19 02:50

> Per-repo commands (TEST_CMD · RUN_CMD · PROFILE) live in `.claude/worktrees.conf`.

## Start here

`rules/workflow.md` is canonical for the 9-phase spine, GATE 0 / GATE 1 / GATE 2, and "How much
process?" — read it first. This page covers only the plugin-side operational specifics those
rules don't: file locations, the Builder brief checklist, and test cadence.

## Conventions & file locations

- **`.claude/worktrees.conf`** — per-repo config (stack profile, TEST_CMD/RUN_CMD, PROFILE).
- **`project-context.md`** — the project "constitution"; produced at GATE 1, loaded by every agent.
- **`docs/superpowers/specs/`** + **`docs/superpowers/plans/`** — design specs + TDD plans (auto-written).
- **`docs/lessons.md`** — the lessons-learned log, appended by `/dev-reflect`.
- **`.git/sdd/progress.md`** — SDD ledger.

## The builder brief

Every implementer dispatch carries this checklist; the implementer self-checks it before
reporting ready:

- a degraded/fail-open path is visible on **stdout** (a hook's `systemMessage`), not only stderr
- a change to a twinned unit (py + node pair) lands in **both** twins, each new test shown failing
  first
- the repo's deterministic doc checks (docs-drift / inventory-count) run in the targeted test slice
- docs describing the changed behaviour ship in the same PR
- a stale-base bypass token goes only on a `git merge origin/main` sync commit, never a normal one

## Test cadence

Keep the behaviour-test suite (web: `e2e/*.spec.ts`; service: integration tests; CLI/lib:
golden/property tests; data: fixture-driven tests) green: run the touched/affected test files
while iterating, and reserve a full suite per PR for a tier-2 PR (tier-0/1 gates on the affected
slice instead) — a single local run under `bin/test-lock` at the final synced head.

## Worktree teardown

Native worktrees are canonical (`EnterWorktree` / Agent `isolation: worktree`, provisioned by the
`worktree_create` hook). Tear one down with `git worktree remove <path>` — the `worktree_remove`
hook backs up untracked files plus an uncommitted-changes patch first, and frees the PORT.
Removal keeps the branch; delete it separately once merged with `git branch -d <branch>`.
Gitignore `.worktrees/` and `worktrees/`.

## See also

`rules/workflow.md`.
