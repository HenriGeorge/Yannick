---
name: conventional-commit
description: 'Generate conventional commit messages from staged changes. Analyzes diff to determine type, scope, and description.'
---

# Conventional Commit

Generate a conventional commit message from the current staged changes.

## Format

```
type(scope): description

[optional body]

[optional footer]
```

## Types

| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes nor adds |
| `test` | Adding or correcting tests |
| `chore` | Build, CI, tooling changes |
| `perf` | Performance improvement |
| `style` | Formatting, whitespace (no code change) |
| `build` | Build system / dependencies |
| `ci` | CI configuration |
| `revert` | Reverts a previous commit |

> These are exactly the types the **commit-msg guard hook** accepts (see Enforcement below) — don't
> invent a type outside this set or the commit will be blocked.

## Process

Run the helper for the DETERMINISTIC facts, then apply JUDGMENT on top of them:

```bash
python3 ~/.claude/skills/conventional-commit/scripts/staged-summary.py
```

It emits JSON — `{files, insertions, deletions, scope_candidates, detected_footers,
subject_length_budget}` — computed straight from `git diff --staged`. Consume it, then:

1. **Type — YOUR call (not the script's).** Read the diff and infer intent: a new capability →
   `feat`, a defect repair → `fix`, doc-only → `docs`, etc. This is the judgment the helper
   deliberately does NOT make.
2. **Scope** — pick from `scope_candidates` (ranked by how many staged files touch each component),
   or override if you know a better module name. `null`/empty = omit the scope.
3. **Subject** — imperative mood, no trailing period, within `subject_length_budget` (≤72, aim ≤50).
4. **Footers** — fold in anything in `detected_footers` (issue refs, `BREAKING CHANGE:`) that belongs
   in this commit; add `Closes #N` / `Fixes #N` as needed.
5. **Body** — add only if the change needs the *why* explained.

## Rules
- Description < 72 characters (the helper's `subject_length_budget.max`).
- Imperative mood: "add" not "added" or "adds".
- Scope is the module: `api`, `cli`, `studio`, `henri`, `pipeline`, `ui` (or a `scope_candidates` entry).
- Breaking changes: add `!` after type or `BREAKING CHANGE:` in footer.
- Reference issues: `Fixes #123` or `Closes #123` in footer.

## Enforcement
The template ships a **commit-msg guard** (PreToolUse·Bash, `hooks/pre_tool_use.py` — H2) that BLOCKS
an inline `git commit -m` whose subject doesn't match
`^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(scope\))?!?: subject`. The helper
never contradicts that grammar — it computes scope/footers/length but leaves the type to you, so a
message you assemble from its output plus a valid type passes the hook. Keep the two in lockstep: if
the hook's type set changes, update the Types table above.

> **Non-duplication (W3):** `staged-summary.py` reports *facts*; the commit-msg hook does the
> *validation*; the *type* is your judgment. The helper must never re-implement the hook's message
> validation — keeping facts and validation in separate tools stops the two from drifting into a
> duplicate check.
