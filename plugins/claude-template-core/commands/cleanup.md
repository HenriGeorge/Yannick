---
description: Clean up stale branches, orphaned worktrees, and merged PRs
---

# Cleanup

Find and clean up stale artifacts from multi-agent runs and old work.

---

## Phase 1: STALE BRANCHES

```bash
git fetch origin --prune
git branch -r --merged origin/main | grep -v 'main$'
git branch --merged main | grep -v 'main$'
```

List branches that are:
- Merged into main (safe to delete)
- Older than 7 days with no open PR
- Local-only with no remote tracking

---

## Phase 2: ORPHANED WORKTREES

```bash
git worktree list
ls -la .claude/worktrees/ 2>/dev/null
```

Identify worktrees that:
- Have no corresponding active agent
- Point to branches already merged
- Are in a detached HEAD state

---

## Phase 2b: PLUGIN INSTALL HYGIENE

If `claude-template` (the dispatcher) is on PATH, run `claude-template plugin-doctor --check` and
report its findings (DEAD / STALE / LEGACY / MAIN-BEHIND entries); offer `--apply` to fix DEAD,
STALE and LEGACY. Otherwise print one line:
`plugin-doctor not available here (vendored/cloud) — skipped`.

---

## Phase 3: CLOSED PRs WITH BRANCHES

```bash
gh pr list --state merged --limit 20 --json number,headRefName,mergedAt
gh pr list --state closed --limit 10 --json number,headRefName
```

Find remote branches that belong to merged/closed PRs.

---

## Phase 4: PRESENT FINDINGS

```markdown
## Cleanup Report

### Branches to Delete ({N})
| Branch | Status | Last Activity |
|--------|--------|--------------|
| {name} | merged/stale | {date} |

### Worktrees to Remove ({N})
| Path | Branch | Status |
|------|--------|--------|
| {path} | {branch} | orphaned/merged |

### Suggested Commands
```bash
# Delete merged local branches
git branch -d {branch1} {branch2} ...

# Delete merged remote branches
git push origin --delete {branch1} {branch2} ...

# Remove orphaned worktrees
git worktree remove {path}
```
```

---

## Phase 5: EXECUTE (with confirmation)

**Ask user before running any deletions.** Present the list and wait for approval.

- Never force-delete (`-D`) — only delete merged branches (`-d`)
- Never delete `main` or `origin/main`
- Clean worktrees with `git worktree remove`, not `rm -rf`
