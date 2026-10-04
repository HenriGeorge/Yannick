---
description: Turn a decision you can't resolve alone into a Markdown questionnaire for the one person who can — filled in async or together. Wraps the mattpocock /to-questionnaire skill.
argument-hint: [the decision / question you're stuck on] (blank = infer from the current context)
allowed-tools: Read, Grep, Glob, Write, Bash(git log:*), Bash(git diff:*)
---

# /questionnaire-me — decision → async questionnaire

**Decision to externalize:** $ARGUMENTS

Use this when a decision is genuinely someone else's to make (a product call, a scope tradeoff, an
external constraint you can't verify) — don't guess it, don't block on it synchronously. Turn it into
a crisp Markdown questionnaire the decision-maker can fill in async or in a meeting.

## What to do
1. **Invoke the mattpocock `to-questionnaire` skill** (installed globally) — it is the reusable
   questionnaire primitive; do not hand-roll one. If it isn't available, fall back to the shape below.
2. Scope the questionnaire to the *actual* open decisions — one section per decision, each with:
   - the decision stated plainly,
   - the options you see (with the tradeoff of each),
   - your **recommendation** + why (so the answerer can just ✓ or override),
   - a blank for their answer + optional notes.
3. Write it to a Markdown file the user can share (`docs/decisions/<slug>-questionnaire.md` or a path
   they name), and tell them where it is.

## Where this fits (the after-skill leg)
This command is the **AFTER_SKILL → questionnaire** step of the skill-runtime lifecycle: run it after a
skill surfaces decisions it can't resolve, to capture them for the human rather than guessing. It pairs
with the up-front `## Interview` convention (the BEFORE_SKILL leg) — see `rules/design-workflow.md`.

**Not a substitute for AskUserQuestion.** For a decision you need answered *now, in-session*, use
AskUserQuestion. `/questionnaire-me` is for decisions that are better answered async by someone else.
