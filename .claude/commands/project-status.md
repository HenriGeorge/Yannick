---
description: Full project status — open issues, PRDs, branches, pipeline state, uncommitted work
---

# Project Status

Gather and present a complete snapshot of where the project stands right now.

---

## Phase 1: GIT STATE

```bash
git status --short
git branch -r --sort=-committerdate | head -15
git stash list
```

Report: uncommitted changes, active branches, stashed work.

---

## Phase 1b: PLUGIN INSTALL HYGIENE

If `claude-template` (the dispatcher) is on PATH, run `claude-template plugin-doctor --check` and
report its findings (DEAD / STALE / LEGACY / MAIN-BEHIND entries). Otherwise print one line:
`plugin-doctor not available here (vendored/cloud) — skipped`.

---

## Phase 2: GITHUB ISSUES

```bash
gh issue list --state open --limit 30
```

Group by labels (bug, feature, enhancement). Count by priority.

---

## Phase 3: OPEN PRDs & PLANS

Check for incomplete PRDs and plans in `.claude/PRPs/` or similar directories:

```
.claude/PRPs/prds/     — any not in completed/
.claude/PRPs/plans/    — any not in completed/
.claude/PRPs/issues/   — any not in completed/
.claude/PRPs/features/ — any not in completed/
```

List each with a one-line summary. Skip if directories don't exist.

---

## Phase 4: OPEN PRs

```bash
gh pr list --state open --limit 20
```

Show: title, author, checks status, conflicts.

---

## Phase 5: REPORTS

Check `.claude/reports/` for recent reports with open items. Skip if directory doesn't exist.

---

## Phase 6: PROJECT-SPECIFIC STATE

If the project has a CLI or status command (check CLAUDE.md), run it to get pipeline/data state. Otherwise skip this phase.

---

## Phase 6b: CLOUD VENDOR STATUS

If `.claude/vendor.lock` exists, run `bin/vendor-tooling.sh . --outdated` and report its lines (an `OUTDATED <plugin>: <ref> → <tag>` per stale pin, or the all-current line). Skip if the file is absent.

---

## OUTPUT FORMAT

```markdown
## Project Status — {date}

### Git
- {uncommitted changes summary}
- {N active branches}

### GitHub Issues: {N open}
- {count} bugs, {count} features, {count} enhancements

### Open PRDs/Plans: {N}
- {list}

### Open PRs: {N}
- {list with status}

### Recent Reports
- {actionable items from reports}

### Suggested Next Steps
1. {most impactful action}
2. {second}
3. {third}
```
