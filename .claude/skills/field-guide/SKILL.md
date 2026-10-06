---
name: field-guide
description: >-
  Orientation map for the claude_template workflow harness — the single-page atlas of how the
  9 phases, 2 gates (Design→Code→Prove), stack profiles, worktrees, hooks, the figma path, agents,
  bin scripts, and WORKFLOW bypass tokens fit together and where each lives. Use when orienting in
  this repo's workflow, asking "where does X live / how do the pieces connect", onboarding to the
  harness, or needing the whole-system map before opening a specific workflow doc. NOT for general
  coding questions unrelated to this harness.
---

# Field Guide — the harness atlas

The fully-enumerated inventory of the claude_template harness lives in one doc. This skill exists
only to surface it on relevance; the content is canonical there, not duplicated here.

## Read the guide

Open **`../../docs/FIELD-GUIDE.md`** (same plugin, `claude-template-core/docs/FIELD-GUIDE.md`). It is
the authoritative index — read it before answering a whole-system "how does the harness fit / where
does X live" question, then follow its links into the depth docs for mechanics.

## What's in it

A whole-system inventory: the two laws, the 9-phase spine, the always-core rules, the hooks (wired
by event) and their H-guards, the bin scripts, plugins, skills, commands and subagents, autopilot /
Ralph / the gate lane, setup.sh and the files a project carries, the fleet & cloud system, lessons &
self-improvement, the WORKFLOW bypass tokens, the sync & drift system, and a doc map. Read it there
for the live counts and rosters rather than relying on this summary.

## Depth docs it points into

`workflow/WORKFLOW.md` (phase mechanics) · `workflow/HOOKS.md` (hook roster) ·
`workflow/ENFORCEMENT.md` (gate roster + bypass tokens) · `AUTOPILOT.md`. Open those for the *how*;
the field guide is the *where* and *what*.

## Done when

You have read `FIELD-GUIDE.md` (or the one section that answers the question) and surfaced the
relevant map/location — not guessed from memory.
