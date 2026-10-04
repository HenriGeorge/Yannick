---
description: "Co-author a ralph todo.md with the user, then hand off to /ralph-loop. The interactive authoring front-end for the low-ceremony autonomous loop — turns a fuzzy goal into independently-finishable, optionally-verifiable steps. Does NOT arm the loop (authoring is a separate phase from the unattended run)."
argument-hint: "[goal / what you want done] (blank = interview from scratch)"
---

# /ralph-plan — co-author a ralph todo, then hand to /ralph-loop

**Goal**: $ARGUMENTS (optional; if blank, the interview draws it out)

The interactive authoring half of the ralph loop. `/ralph-loop` runs a `todo.md` unattended — but a
run only succeeds if the list has the *right* items: each one independently finishable, with an
obvious done-state, ideally carrying a cheap `| verify:` check. That scaffolding is where a long run
lives or dies, and it's the hard part. This command builds that list *with* you.

> **Two phases, never one invocation.** Authoring is interactive; the loop is unattended. `/ralph-plan`
> ONLY writes the todo and hands off — it does **not** call `bin/ralph-arm` / arm the loop. You review
> the list, then run `/ralph-loop <path> <max>` yourself to go unattended. (Interactive skills like
> `interview-me` cannot run inside the unattended loop, so the seam is deliberate.)

## Steps

1. **Interview for intent (lightweight).** Draw out what "done" means — one question at a time, each
   with your best guess attached (reuse `interview-me`'s method; scale it *down* — a todo doesn't need
   95%-confidence rigor). Resolve: the outcome, who/what it's for, and the binding constraint. If
   `$ARGUMENTS` already states the goal clearly, confirm it in one line and skip ahead.
2. **Decompose into loop-ready items.** Break the goal into steps where **each is one independently
   finishable pass** with a self-evident done-state — not "build the feature" but the concrete
   sub-steps that add up to it. If a step can't be finished in one focused pass, split it. (This is
   the judgment the loop can't make for itself — `bin/ralph-arm` only checks the list is non-empty.)
3. **Suggest an optional `| verify:` per item.** For any step with a cheap, deterministic check,
   propose it inline: `- [ ] add /health → 200 | verify: curl -sf localhost:$PORT/health`. Rules the
   author must respect: fast (8s cap), **idempotent** (the loop retries a failing verify once, so it
   may run more than once), and success-only (exit 0 = met). A step with no good check stays
   self-attested — don't invent a weak one.
4. **Confirm the draft, then write it.** Show the full `todo.md` and get an explicit yes (fold in
   corrections and re-show). Write it to a path the user picks (default `./ralph-todo.md`).
5. **Hand off — do not arm.** Tell the user the exact next command to go unattended:
   `/ralph-loop <path> <max-iterations>`. State plainly that `/ralph-plan` did NOT arm the loop; the
   run starts only when they invoke `/ralph-loop`.

## A good ralph todo (the shape you're aiming for)

```markdown
# Add a /health endpoint
- [ ] add GET /health returning 200 + {status:"ok"} | verify: curl -sf localhost:$PORT/health
- [ ] unit-test the handler | verify: npm test -- health
- [ ] document it in the README
```

Each line one finishable step; a `| verify:` where a cheap check exists; self-attested otherwise.

## See also

`/ralph-loop` (the unattended run this hands off to) · the `gates` skill (the command-verified,
higher-rigor lane) · `interview-me` (the intent-extraction method reused in step 1).
