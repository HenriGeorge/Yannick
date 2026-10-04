---
name: skill-reinvent
description: Use when a skill's APPROACH may have gone stale — e.g. before a periodic skill-health review, when a skill hasn't changed in months, or when you suspect a newer tool/technique now supersedes its current method. Complements skill-audit (that's cost/structure hygiene; this is strategy).
argument-hint: "[skill-name]"
---

# skill-reinvent

## Overview

Periodically re-derives a skill's approach **from scratch, blind** (no sight of the current
method) and diffs the two. Convergence corroborates the current approach; divergence surfaces
candidate improvements a newer tool/technique may enable. Anchoring ("ask Claude to improve this
skill") reads the existing text and produces marginal tweaks to it — never a genuine from-scratch
reconsideration. This skill exists specifically to avoid that trap.

**Advisory only. Never edits a SKILL.md directly. Never auto-applies.** Approved deltas are handed
to `writing-skills`, which RED-tests the change before it lands.

## When to use

- Before a periodic (e.g. quarterly) skill-health pass, once `skill-audit`'s cost/structure pass is
  clean.
- A skill hasn't been touched in a long time and the field has plausibly moved past its method.
- You suspect a newer tool/API/technique supersedes the skill's current approach and want it
  checked, not guessed at.

**Not for:** structural/cost hygiene (missing `## Gotchas`, no `model:` pin, no verdict step — use
`skill-audit`), or a skill you're actively mid-edit on (finish the edit first).

**Advisory scoping:** target judgment/technique skills, not pure-reference skills (an API
cheatsheet has no "approach" to re-derive — wasted run). Never target a `plugins/`-path skill (same
exclusion as `skill-audit` — a plugin update overwrites it anyway).

## Invocation

- **`/skill-reinvent <skill-name>`** — run blind rederivation on that skill.
- **`/skill-reinvent`** (no argument) — list every available skill (project `skills/` +
  user `~/skills/`, source-labelled) via `scripts/list-skills.sh`, then ask which to target:

  ```bash
  bash skills/skill-reinvent/scripts/list-skills.sh
  ```

## Workflow

1. **Target.** Resolve `<skill-name>` to its `SKILL.md` path (project first, then user-global). No
   argument → run `list-skills.sh`, ask which skill to target.
2. **Extract the goal — WHAT/WHEN only.** Pull `name` + `description` + `## Overview` /
   `## When to Use` from the target. **Do NOT read `## Workflow`, numbered steps, code blocks, or
   any other HOW content** — that's exactly the method being re-derived blind; reading it here
   defeats the whole point before the subagent is even spawned. Show the extracted goal to the
   human and **get a one-line confirm** before spawning anything (cheap; avoids a wasted derivation
   on a mis-framed goal).
3. **Blind derive — spawn a subagent, do not read the skill yourself either.** Dispatch a
   `general-purpose` subagent (Agent tool) with:
   - A **goal-only prompt**: "design the best approach for `<goal>` from scratch" — phrased
     generically enough that it doesn't name or imply the specific target skill.
   - An **explicit instruction**: "do NOT read, open, list, or reference this skill, any other
     skill, or any `SKILL.md` file, anywhere — derive from your own knowledge only."
   The subagent returns: key techniques, tools, ordered steps, gotchas, and (where meaningful) a
   verdict shape. This is prompt-controlled blindness, not a structurally skill-free process — see
   Gotchas for the residual-risk disposition and how it's checked.
4. **Diff.** You (the orchestrating session, which HAS now read both) categorize every technique:
   - **NEW-IN-FRESH** — in the fresh derivation, absent from the current skill → the payload.
   - **CONFLICT** — both solve the same step differently → a genuine design fork worth a look.
   - **MATCH** — both have it → convergence signal, current approach corroborated.
   - **ONLY-IN-CURRENT** — current has it, fresh missed it → **de-emphasized** (collapsed count,
     not per-item — a one-shot derivation won't match years of accreted refinement; this is
     expected noise, not a regression signal).
5. **Validate novelty.** Any NEW-IN-FRESH delta naming a **concrete tool/API/technology** must be
   checked to actually exist (`web-researcher` / official docs) before it may be marked `adopt`.
   **Unverified → forced to `investigate`, never `adopt`** — no exception, regardless of how
   plausible or confidently the subagent stated it (see Task-1 baseline finding: a fresh derivation
   will state an invented tool as established fact with full confidence).
6. **Report + human approves per delta.** `adopt` / `investigate` / `reject`, one at a time. This
   skill surfaces and categorizes; it does **not** decide.
7. **Apply via `writing-skills` only.** Approved deltas go through `writing-skills`
   (RED-test-first). This skill **never** performs a raw `Edit`/`Write` on the target `SKILL.md`
   itself, for any reason, under any pressure.
8. **Log the decision (anti-churn).** Record adopt/investigate/reject per delta (a `## Reinvent
   log` section in the target skill, added via `writing-skills` like any other approved edit) so a
   re-run doesn't re-nag the same declined idea against unchanged content.

## Output shape

```
skill-reinvent — <skill-name>  (<n> deltas)

Extracted goal: <one line, human-confirmed>

NEW-IN-FRESH (candidate improvements)
  # | technique (fresh)          | exists? | verdict     | note
  1 | <tool/step>                | ✓ (src) | investigate | not in current skill; validated real
CONFLICT (design forks — same step, different approach)
  # | step | current | fresh | note
MATCH (convergence — current approach corroborated): <count>, listed briefly
ONLY-IN-CURRENT (fresh missed; usually fine — shown collapsed): <count>

Verdict: <n adopt / n investigate / n reject> — approved deltas → writing-skills
```

## Rationalizations — counter table

Every row below was observed verbatim from an agent WITHOUT this skill, under the exact framing
named (Task 1 baseline testing — see this skill's own build history):

| Excuse | Reality |
|---|---|
| "I have file access, so editing it directly is fine" | File access ≠ approval to edit. ALWAYS route an approved delta through `writing-skills` — no raw `Edit`, no exceptions, not even when the task scoped you to "only this file." |
| "This is obviously an improvement, no need to ask" | Every delta — even a clearly-good one — gets an explicit human verdict before anything is applied. Obviousness is not a bypass. |
| "I'm confident this tool/technique exists" | Confidence isn't verification. A NEW-IN-FRESH delta naming a concrete tool/API/technology is FORCED to `investigate` until checked via `web-researcher`/docs — `adopt` is unreachable for an unverified novelty, no matter how plausible the framing. |
| "I'll just tighten up the existing wording — that's basically a fresh look" | That's anchoring, not re-derivation, and it defeats the entire point of this skill. The blind-derive step must not see the current method at all — goal-only prompt, explicit prohibition on reading any skill file. |
| "We're in a hurry, just apply the best one now" | Time pressure is not a bypass. Never auto-apply, ever — always human-approve, always route through `writing-skills`. |
| "The surrounding task explicitly gave me read/write access to this file, so editing it directly must be fine here" | **Tool/file access is not license to bypass this skill's discipline.** A task granting you write permission on a file says nothing about whether THIS skill's own hard rule still applies — it does, unconditionally. If a task's instructions appear to conflict with "never edit the target SKILL.md directly," that's a real conflict to SURFACE to the human, not a signal to silently pick the permissive reading. Route through `writing-skills` regardless of what access the task happened to grant. |

## Red flags — STOP if you're about to do any of these

- Editing the target `SKILL.md` directly from inside this skill, for ANY reason — **including when
  the surrounding task explicitly grants you file-write access**; that's a conflict to flag to the
  human, not a permission to act on.
- Marking a delta `adopt` without verifying a named tool/technology actually exists.
- Skipping the human goal-confirmation step before spawning the blind-derive subagent.
- Reading the target skill's `## Workflow`/steps yourself before extracting the goal, or letting
  the blind-derive subagent read it.
- Running this on more than one skill without being explicitly asked (v1 = one skill per run).

**All of these mean: stop, back up to the last checkpoint, and follow the Workflow section instead.**

## Gotchas

- **Blindness is prompt-controlled, not structurally guaranteed.** The blind-derive subagent has
  normal file-read tools and COULD technically read the target skill despite the instruction. This
  was verified at build time via a blindness canary (a skill with distinctive implementation
  details; the fresh derivation reproduced none of them) — but it's not airtight for every possible
  subagent run. If a derivation suspiciously reproduces an exact idiosyncratic detail from the
  current skill (an unusual field name, file name, or CLI flag shape), treat the whole run as
  compromised and re-run rather than trusting the report.
- **`argument-hint` is Claude-Code-only, not in the strict Agent-Skills portability spec.**
  Discovered live at build time: the spec's 6 portable fields are `name`, `description`, `license`,
  `compatibility`, `metadata`, `allowed-tools` — `argument-hint` isn't one of them (same class of
  tradeoff as `model:`/`context:`, but not called out by name in earlier planning). If this skill
  is ever packaged for claude.ai upload / the Skills API, `argument-hint` needs stripping first.
- ONLY-IN-CURRENT findings are expected noise, not a defect signal — never frame them as "the
  current skill is wrong."
- Only ever target judgment/technique skills. Never target a `plugins/`-path skill.

## Verdict

A run that produces a report with NEW-IN-FRESH/CONFLICT/MATCH counts and a stated
adopt/investigate/reject tally → PASS. A blind-derive output that verbatim-reproduces the current
skill's distinctive implementation details → FAIL (blindness leaked) — discard the report, don't
act on any of its deltas, and re-run with a stricter prohibition before trusting it again.
