---
description: "Point at an ad-hoc todo.md and walk away — arm the low-ceremony autonomous loop that works the list until every box is ticked. The lightweight lane of build_loop; for command-verified rigor use the gates skill."
argument-hint: "<todo-path> <max-iterations>"
---

# /ralph-loop — point at a todo, walk away

**Args**: `$ARGUMENTS` → `<todo-path> <max-iterations>` (both required).

The low-ceremony lane of `build_loop` (the repo's Ralph-pattern stop-hook engine): no plan under
`docs/superpowers/plans/`, no `.gates.md` ledger, no `gate-run arm`. Just a todo.md and a stop
budget. Each time you try to stop, the Stop hook re-feeds the next unchecked item until the whole
list is done — then it self-disarms.

> **When to use the OTHER lane instead:** if "done" must be command-verified with human-approved
> checks, use the **`gates` skill** (`autonomy: unattended` plan + a `.gates.md` ledger). This lane
> trades that rigor for ergonomics — ticks are self-attested unless a line carries an inline
> `verify:` (see below).

## Run it

1. **Arm** — run the arm script with the args verbatim:
   ```bash
   bin/ralph-arm $ARGUMENTS
   ```
   It refuses (non-zero) if `<max-iterations>` is missing/non-numeric, the todo file is absent, or
   it has no unchecked `- [ ]` boxes. On success it writes `.claude/ralph-state.json`.
2. **Work the list.** Take the first unchecked `- [ ]` item, implement it, and — if the line carries
   `| verify: <shell>` — run that command and only tick the box when it exits 0. Then move to the
   next item. Do not stop until every box is ticked.
3. **Walk away.** On each stop the hook checks the list: unchecked item left → it re-feeds that item;
   all ticked but a `verify:` still failing → it re-feeds that fix; all ticked and green → it deletes
   the state file and lets the session end.

**Terminators (inherited from `build_loop`):** the run parks to `.claude/NEEDS-HUMAN.md` on budget
(`<max-iterations>` stops), a 3-stop stall with no progress, or a livelock (same block twice, no new
commit). Create `.claude/NEEDS-HUMAN.md` yourself to hand back early.

**Session-scoped:** the state binds to the first stop's session, so an abandoned run never drives a
later, unrelated session. Delete `.claude/ralph-state.json` to clear a stale one.

## Writing a good ralph todo

The loop is only as good as the list. Each item should be **one independently-finishable step** with
an obvious done state — not "build the feature" but the concrete sub-steps that add up to it.

```markdown
# Add a /health endpoint
- [ ] add GET /health returning 200 + {status:"ok"} | verify: curl -sf localhost:$PORT/health
- [ ] unit-test the handler | verify: npm test -- health
- [ ] document it in the README
```

- `- [ ] <task>` — self-attested; the agent ticks it when done (trusted).
- `- [ ] <task> | verify: <shell>` — the hook runs `<shell>` (exit 0 = pass) before the tick counts;
  a failing verify re-feeds the item. Use it on anything with a cheap, deterministic check.
- Keep verify commands fast (8s timeout) and idempotent — they may run more than once.
- Right granularity: if an item can't be finished in one focused pass, split it.

*(Prefer to build the list together? Run `/ralph-plan` first — it co-authors the todo with you and
hands off here. Or write it yourself and arm directly.)*
