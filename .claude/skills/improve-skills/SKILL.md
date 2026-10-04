---
name: improve-skills
description: Use when the user runs `/improve-skills [skill|all]`, or asks to action/apply skill-improvement proposals that `skill-audit`, `skill-reinvent`, or `/dev-reflect` surfaced but never applied — also when such notes rot unactioned in `docs/lessons.md`, and at CLOSE right after `/dev-reflect` (offered, not auto-run). The proposal→apply executor: consumes those three sources and drives each human-approved change through `writing-skills`; never proposes new improvements, never auto-applies.
argument-hint: "[skill|all]"
---

# improve-skills

## Overview

Three tools *propose* skill changes — `skill-audit` (structure/cost), `skill-reinvent`
(strategy), `/dev-reflect` (session "Process improvements" rows). One tool *applies* them —
`writing-skills`. **Nothing bridges proposal→apply**, so a skill improvement found in
one session rots in `docs/lessons.md` action items or a scan output nobody re-opens. `/improve-skills`
is that missing executor: it consolidates the three sources into one ranked, deduped queue and drives
each **human-approved** change through `writing-skills`.

**Core principle — never auto-apply.** Human verdict per change; zero approvals → zero `SKILL.md`
edits. It proposes nothing new (that is the three sources' job) and hand-edits no skill (that is
`writing-skills`' job). It only *lands* what already exists — the find/land split.

## When to use

- `/improve-skills [skill|all]` invoked manually, anytime.
- Offered (never auto-run) at CLOSE, right after `/dev-reflect`.
- Skill-improvement notes keep accumulating unactioned across sessions.

**When NOT to use:** to *discover* new skill improvements (use `skill-audit` / `skill-reinvent`), or
to promote recurring *lessons* into hooks/rules (that is `/improve`, a different target + engine).

## Interview

Choice-taking skill → run this BEFORE gathering. Ask **one `AskUserQuestion` at a time**, in order;
each has a recommended default. Skip a question only if the invocation argument already answers it
(`/improve-skills grill-me-interview` pins scope to one skill).

1. **Scope** — one named skill, or `all`? **Default: the argument; else `all`.**
2. **Sources** — which of the three to pull? (a) all three · (b) `/dev-reflect` rows only · (c) the
   two scanners (`skill-audit` + `skill-reinvent`) only. **Default: all three.**
3. **Aggressiveness** — (a) structure/cost only (`skill-audit` rows) · (b) strategy too
   (`skill-reinvent` deltas) · (c) both + session-failure rows. **Default: both + session failures.**
4. **Apply-batch size** — how many approved changes to action this run (1 / 3 / all queued). Bounds
   the `writing-skills` cost. **Default: 3.**

## Workflow

### 1. Gather (read the three sources — never fabricate)

- **`/dev-reflect`** — parse **every** `## Session:` block in `docs/lessons.md` whose "Process
  improvements" `Skill/command` rows are not yet actioned/declined in `docs/improve-skills-log.md`
  (not just the latest block — older un-actioned proposals rot otherwise). Defensive parse: **skip an
  unparseable row, never invent a proposal** — but **surface every skipped row** (a count + its
  `lessons.md:<line>` refs) in the run summary, so a real human-authored proposal that fails to parse
  is visibly dropped, never silently swallowed. The log is the dedup key, so re-scanning all blocks is
  idempotent.
- **`skill-audit`** — read its last output for the target skill(s); if none exists, RUN it (cheap,
  deterministic scan) → structure/cost rows.
- **`skill-reinvent`** — read its reinvent-log deltas for the target skill(s). Do **not** blind-re-run
  it (it is heavy) unless the human asks.

### 2. Consolidate

- Dedup by `(skill, concern)` — the same concern from two sources collapses to ONE queue item citing
  both.
- Rank by signal strength: a real session failure (`/dev-reflect`) outranks a structural nit; a
  `Seen ≥Nx`-recurring lesson outranks a one-off.
- Drop any item logged in `docs/improve-skills-log.md` as **declined against unchanged content** (its
  target's content-hash matches the current file — see anti-churn).

### 3. Present + apply (one item at a time)

Per queued item, **one `AskUserQuestion`**: approve / skip / defer. On **approve**:

1. Invoke **`writing-skills`** for that **targeted edit** (the change the proposal
   describes — not a full skill re-author).
2. Verify the edited skill still parses (valid frontmatter, no broken structure) and run its declared
   verify step if it has one.
3. **If verify FAILS** — surface the failure and do **not** record `actioned`: leave the edit
   uncommitted for the human and record the attempt as `failed` (so the concern is neither lost nor
   suppressed by a content-hash the broken edit produced). Only on verify success →
4. Record the outcome in `docs/improve-skills-log.md`: `actioned`, plus the target's **content-hash**
   (`git hash-object <skill>/SKILL.md`, whole file) and the source(s).

Verdict → log outcome:
- **skip** → `declined` + content-hash → suppressed until the target changes (anti-churn).
- **defer** → `deferred` (NOT `declined`, NOT hash-suppressed) → re-surfaces on the next run, because
  "revisit later" must actually come back. Never fold `defer` into `declined` — a deferred item that
  silently never returns is the failure this distinction prevents.

### 4. Self-edit guard

A proposal targeting **`writing-skills`** (the engine) or **`improve-skills`** (this skill) needs an
EXTRA `AskUserQuestion` naming the self-target explicitly, PLUS a post-edit smoke check before the
change is kept: the edited `SKILL.md` parses AND a trivial dry-run reaches its first `AskUserQuestion`
without erroring. A structurally-broken self-edit would break the applier — the guard catches that,
not a taste regression (the human approval covers taste).

## Anti-churn (the log)

`docs/improve-skills-log.md` is a central ledger keyed `(skill, concern, content-hash-of-target)`.
A `declined` row suppresses re-proposal **only while the target's content-hash is unchanged**; once
the skill changes, the concern is eligible again. Central (not per-skill) so dedup spans all three
sources and all skills. Never hand-edit the log for suppression — decline through this skill so the
hash is captured correctly.

## Common mistakes

- **Hand-editing a `SKILL.md` directly.** Every edit routes through `writing-skills` (workflow.md Adherence
  #7). This skill orchestrates and gates; it never writes skill content itself.
- **Reading only the latest `/dev-reflect` block.** Scan every un-actioned block; the log makes it
  idempotent.
- **Fabricating a proposal from a malformed row.** Skip it. A proposal must trace to a real source row.
- **Blind-re-running `skill-reinvent`.** Read its log; it is the heavy, deliberate strategy tool.

## Red flags — STOP

- About to edit a `SKILL.md` without going through `writing-skills`.
- About to action a self-edit (`writing-skills` / `improve-skills`) without the extra confirmation +
  smoke check.
- A queue item cites no source row → you fabricated it. Drop it.
- Zero human approvals but a `SKILL.md` changed → auto-apply leaked. That is a defect.

## Verify

- `skill_nudge` does NOT WARN — the `## Interview` block satisfies the choice-taking-skill convention.
- A run with **zero human approvals** changed **zero** `SKILL.md` files (`git status` clean for
  `plugins/**/skills/**`).
- Every actioned/declined item has a `docs/improve-skills-log.md` row with a content-hash.
- No `model:`/`--model` bare alias in any edit this skill authored.
