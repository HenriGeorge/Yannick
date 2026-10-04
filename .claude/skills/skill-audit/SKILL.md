---
name: skill-audit
description: Use when reviewing this project's skills/ for staleness — a skill missing a min-viable model:, a deterministic procedure that should be a script, a missing ## Gotchas section, a missing pass/fail verdict step, or a skill that should gather input via AskUserQuestion instead of assuming it. Also use for a periodic/weekly skill-health pass, or reactively when the user says "patch the skill I just used" for one named skill.
---

# skill-audit

## Overview

Scans this project's `skills/**/SKILL.md`, proposes cost/quality improvements per skill,
and hands off every APPROVED change to `writing-skills`. It never edits a SKILL.md
directly and never auto-applies anything — the review table is a starting point for a human
decision, one row at a time. Re-runnable; declined rows don't get re-proposed until the file
changes. Complements #112 (skill-linter) and #113 (description shortenings) — this skill covers
model/context cost-awareness + gotchas/verdict hygiene, not linting or description quality.

## When to use

- A skill feels expensive to run for what it does (deterministic scan, fixed format check) — check
  whether it should pin a cheaper `model:`.
- Before a periodic skill-health review.
- After adding several new skills and wanting a batch sanity check.

**Not for:** editing a skill directly (use `writing-skills`), or linting descriptions
(#113) or general skill quality issues unrelated to cost/gotchas/verdict (#112 skill-linter).

## Workflow

1. Run the scan script (defaults to the project's `skills/`; add `--global` yourself by
   pointing `--root ~/.claude/skills` explicitly — never scan or touch a `plugins/`-shaped path,
   the script excludes those unconditionally):

   ```bash
   python3 skills/skill-audit/scripts/audit.py
   ```

   Add `--json` for machine-readable rows, or `--root <dir>` to point elsewhere.

2. Present the table to the human, **one row per skill**, each proposal flagged individually:
   - `recommend_model: haiku` — only when the skill reads as pure grunt work (scripted, no
     evaluative language). A row with `portability_warning: true` means applying it adds a
     Claude-Code-only frontmatter field to a skill not already committed to being
     Claude-Code-only — the Agent-Skills spec (claude.ai upload / Skills API / `package_skill.py`)
     hard-fails on unrecognized frontmatter fields, so call this out explicitly before the human
     approves.
   - `context_fork_candidate: true` — the skill's steps don't reference back into the parent
     conversation; same portability caveat applies.
   - `script_candidate: true` — 3+ numbered steps read as a fixed procedure with no script backing
     them yet.
   - `missing_gotchas` / `missing_verdict` — booleans.
   - `askuserquestion: true` — the skill would benefit from gathering input via `AskUserQuestion`
     instead of assuming it; propose the 1–3 clarifying questions that skill should ask.
     Recommend-only, same as every other row — an approved change still hands off to
     `writing-skills`.

3. For each row the human approves, apply the edit via `writing-skills` (never a raw
   `Edit` on the SKILL.md from inside this skill — that methodology owns writing/testing any
   generated script and keeps the SKILL.md's own TDD discipline intact).

4. For each row the human declines, record it so the NEXT run doesn't re-propose the same finding
   for the same file content:

   ```bash
   python3 skills/skill-audit/scripts/audit.py --decline <relative/SKILL.md/path> <finding_key>
   ```

   `finding_key` is one of `model`, `context_fork`, `script_candidate`, `gotchas`, `verdict`,
   `askuserquestion`.
   Editing the skill afterward (content hash changes) clears that decline automatically — it isn't
   a permanent suppression.

## Reactive mode (patch a skill after a mistake)

Triggered by "patch the skill I just used" or a mistake surfacing mid-session — distinct from the
full scan above.

- **Requires a named skill.** If the user doesn't name one, ASK which skill — never guess "the
  skill I just used"; a wrong guess proposes a patch to the wrong file.
- **Skips the full scan.** Read only THIS conversation plus the one named skill's SKILL.md, and
  propose two things: (a) a `## Gotchas` entry capturing the exact edge case that just occurred,
  (b) any structural fix the mistake reveals (missing verdict step, wrong assumption baked into a
  Workflow step, etc).
- **Same invariants as the scan:** recommend-only, never auto-edit — an approved proposal still
  hands off to `writing-skills`.

## Quick reference

| Finding | What it means | Before approving |
|---|---|---|
| `recommend_model` | proposed min-viable `model:` | check `portability_warning` |
| `context_fork_candidate` | skill looks context-independent | check `portability_warning` |
| `script_candidate` | numbered steps, no script backing them | writing-skills authors + tests the script |
| `missing_gotchas` | no `## Gotchas` section | only add if the skill has actually accumulated a real gotcha — an empty placeholder section is worse than none |
| `missing_verdict` | no explicit pass/fail step | only meaningful for skills with a real success/failure outcome |
| `askuserquestion` | skill takes an `argument-hint`/choice-y language but never uses `AskUserQuestion` | only add if the skill genuinely needs to gather a choice from the user mid-run |

## Common mistakes

- **Auto-applying a row.** Never — always route through `writing-skills`, always ask
  first.
- **Adding `model:`/`context:`/`effort:` to a skill meant to be uploaded via the Agent-Skills spec**
  (claude.ai / Skills API). Those fields are Claude-Code-only and the spec hard-fails on unknown
  frontmatter. This is exactly what `portability_warning` exists to catch — don't wave it away.
- **Re-nagging on a declined finding.** If the table proposes something already declined for the
  current file content, the decline-state file (`skills/skill-audit/.audit-state.json`) is
  stale or wasn't passed via `--state-file`/default location — check that first, don't just approve
  again to make it go away.
- **Scanning plugin-cache skills.** The script already excludes any path with a `plugins` segment;
  if you need to review a plugin's bundled skill, that's a PR to the plugin's own repo, not this
  project.

## Gotchas

- The `recommend_model`/`context_fork_candidate` heuristics are conservative by design (default to
  "no change" on ambiguous signal) — a "no proposal" row doesn't mean the skill is optimal, it means
  the heuristic wasn't confident enough to suggest one. Judgment calls still need a human read of
  the skill, not just the table.
- The decline-state file is local scratch state, not meant to be fought over between team members —
  if you re-run this after someone else's decline, you'll see their declines too (the state file is
  shared/git-tracked scratch, same as any other project file).

## Verdict

Scan completed and printed a table (or JSON) with zero uncaught errors → PASS. A traceback or a
row silently missing an expected field → FAIL, treat as a bug in `scripts/audit.py`, not in the
skills being scanned.
