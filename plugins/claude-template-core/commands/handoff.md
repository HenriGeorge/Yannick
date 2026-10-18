---
description: "Write a HANDOFF.md for session continuity — captures current state, decisions, and next steps so the next session can continue without clarifying questions."
argument-hint: "[optional: brief description of what was being worked on]"
---

# Session Handoff

**Context**: $ARGUMENTS (optional; will be derived from git state if empty)

---

## Purpose

Capture the **continuation state** of the current session so a fresh session (or a different person) can pick up exactly where you left off — without asking clarifying questions.

This is NOT a reflection (use `/dev-reflect` for lessons learned). This is a **snapshot of where things stand and what to do next**.

## When to Use

- Before ending a long session that isn't finished
- When context is getting compressed (you notice repeated work or forgotten details)
- Before handing off to another developer or agent
- At the end of any session touching >10 files where work continues tomorrow
- When you realize you need a fresh session to continue cleanly

---

## Phase 1: GATHER STATE

```bash
# Current branch and status
git branch --show-current
git status --short

# What changed in this session
git diff --stat HEAD 2>/dev/null || git diff --stat origin/main
git log --oneline --since='6 hours ago' | head -15

# Uncommitted work
git diff --name-only

# Any active plans or state files
ls .claude/state/$(git branch --show-current)/ 2>/dev/null
ls .claude/PRPs/plans/*.md 2>/dev/null | tail -5
```

Also check for:
- Running processes or servers that the next session needs
- Open PRs that need review or are blocking
- Test failures that still need fixing

---

## Phase 2: WRITE HANDOFF.md

Write to `HANDOFF.md` in the **MAIN checkout root** — the persistent working tree, **NOT** the current
directory. When you run this inside a `cc-worktrees` worktree, the worktree root is **ephemeral**:
`cc-worktrees rm` force-deletes it, and HANDOFF.md is never committed (see Phase 3), so a handoff
written into the worktree is **LOST** on cleanup (lessons #12/#28). Always resolve the main checkout
and write there:

```bash
# The MAIN working tree is the FIRST entry of `git worktree list` — it persists across worktree rm.
MAIN=$(git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}')
MAIN=${MAIN:-$(git rev-parse --show-toplevel 2>/dev/null)}   # fall back to repo root
MAIN=${MAIN:-$PWD}                                            # fall back to cwd if not a git repo
HANDOFF="$MAIN/HANDOFF.md"
echo "handoff target: $HANDOFF"
```

Write to `$HANDOFF` (overwrite any existing one — it's a living document, not a log). In a plain
(non-worktree) repo this is just the repo root, exactly as before; in a worktree it lands in the
persistent main folder so it survives `cc-worktrees rm`.

**Hard constraint: under 100 lines.** Be concise, not exhaustive. The next session will read code and git log for details — HANDOFF.md provides the map, not the territory.

```markdown
# Handoff — YYYY-MM-DD

## Goal
[One sentence: what were you trying to accomplish?]

## Branch
`<branch-name>` — [status: clean / dirty / has uncommitted work]

## What's Done
- [Completed task 1]
- [Completed task 2]
- [PR #N merged/opened — brief description]

## What's In Progress
- [Current task — where you stopped, what file you were editing]
- [Blockers if any]

## Key Decisions Made
- [Decision]: [Why — one sentence rationale]
- [Decision]: [Why]

## Failed Approaches (Don't Retry These)
- [What you tried]: [Why it didn't work]

## Current Health
- Tests: [passing / N failures in <file>]
- Lint: [clean / N errors]
- Build: [passing / broken because <reason>]
- Server: [running on port N / not started]

## Next Steps (in order)
1. [First concrete action — be specific: "Fix the type error in arrange.py:145"]
2. [Second action]
3. [Third action]

## Files to Read First
- [Most important file for context]: [Why]
- [Second file]: [Why]
```

### Quality Checklist

Before writing, verify:
- [ ] Could someone continue from this without asking you anything?
- [ ] Are the "Next Steps" concrete enough to start immediately?
- [ ] Are failed approaches documented so they won't be retried?
- [ ] Is the health section accurate (run the checks, don't guess)?
- [ ] Is it under 100 lines?

---

## Phase 3: SIGNAL THE HANDOFF

After writing:

```bash
# Show what was written (use the resolved $HANDOFF from Phase 2, not a bare relative path)
echo "--- HANDOFF.md written ---"
wc -l "$HANDOFF"
head -5 "$HANDOFF"
```

Tell the user:
- The handoff is ready at `$HANDOFF` (name the **full path** — in a worktree this is the MAIN checkout, not the worktree)
- Whether there's uncommitted work that should be stashed or committed first
- Suggest: "Start your next session with: read HANDOFF.md" (from the main checkout)

**Do NOT commit HANDOFF.md** — it's ephemeral (a relay baton, not a historical record). Writing it to
the **main checkout root** (Phase 2) is what keeps it safe *without* committing it: the main working
tree persists across `cc-worktrees rm`, so the handoff survives a worktree cleanup even though it
never enters git.

---

## Integration with Other Commands

| Command | What it captures | When |
|---|---|---|
| `/handoff` | **Where to continue** — state, decisions, next steps | End of incomplete session |
| `/dev-reflect` | **What to learn** — wins, lessons, process improvements | End of completed session |
| `/prp-commit` | **What changed** — conventional commit with context | After each logical unit of work |

A session that finishes its goal uses `/dev-reflect`. A session that runs out of time uses `/handoff`. They complement each other — use both if a session has lessons AND continuation state.
