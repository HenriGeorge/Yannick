---
name: gates
description: Use when making a plan's "done" command-verified instead of self-attested — authoring a GATES.md acceptance ledger and proving each gate with real command evidence before claiming complete. Triggers on "gates", "GATES.md", "gate-verified done", or a plan that carries a `gates:` frontmatter key.
---

# gates — command-verified completion

A plan box is normally ticked on the agent's say-so. This skill closes that gap: a plan with a
`gates:` frontmatter key is "complete" only when every gate in its ledger has **real,
command-verified evidence**. The executor is the vendored `claude-template gate-check`; you drive it
through `claude-template gate-run`, which pins a canonical env so a gate run is reproducible.

## The loop

```mermaid
flowchart LR
    A["author GATES.md<br/>(before work) + gates: in the plan"] --> C["agent works next box"]
    C --> D["claude-template gate-run verify<br/>re-runs the gates"]
    D --> E{"gate met?<br/>exit 0 AND EXPECT matched"}
    E -->|no| C
    E -->|yes| F["tick the box"] --> G{"all gates evidenced?"}
    G -->|no| C
    G -->|yes| H["done → pr_gate + review panel gate the land"]
```

## Steps

1. **Author the ledger BEFORE work.** Copy `templates/GATES.md` to
   `docs/superpowers/plans/<plan-basename>.gates.md`, one gate per plan checkbox. Add
   `gates: docs/superpowers/plans/<plan-basename>.gates.md` to the plan frontmatter.
2. **Author gates that can FAIL.** Each runnable gate observes the outcome directly and its `EXPECT:`
   is a **success-only marker** the CHECK prints *after* every assertion passes — never a word that
   failure output also contains. Measure numbers from source; never copy a briefed figure into `EXPECT:`.
   **A fix-present CHECK must anchor on the real fix locus, not a loose grep (#533).** When a gate asserts
   that a fix is present, match it against the specific function/range/structure the fix lives in (e.g. the
   exact line in the target function, an AST/structural match, or a `grep` scoped to that block) — a bare
   or window-less `grep` for the keyword matches an unrelated mention (a comment, a test name, a sibling
   caller) and passes falsely, so the gate reports "fixed" when it isn't. Prove the CHECK fails on the
   pre-fix code first. Lint: `claude-template gate-lint <ledger>` (fix errors; sharpen on warnings).
3. **Use only canonically-available tools in a CHECK.** `claude-template gate-run` pins `PATH` to
   `node`'s dir + `/usr/bin:/bin` + `~/.local/bin` (the `claude-template` dispatcher dir, so a CHECK may
   invoke `claude-template <helper>`) + the repo `bin/`, and `UNLAZY_SHELL=/bin/sh`. A CHECK that reaches
   for a tool outside that PATH will fail (correctly) rather than pass unreproducibly.
4. **Verify, then tick.** After finishing a box run `claude-template gate-run verify <ledger>` — it
   re-runs the gates and refreshes `EVIDENCE:`. Tick a plan box only when its gate is met. **A checked
   box with `EVIDENCE: pending` is UNMET.**
5. **Abandon honestly.** If a gate is genuinely impossible, keep it and add `ABANDON: G<n> <reason>` at
   column 1. It is a terminal HANDOFF, never a pass; never promote an abandoned gate to "complete".

## Interview

Run these one at a time (AskUserQuestion) before authoring the ledger:

1. **What is the ONE observable outcome that means this plan actually worked?** (Recommended: the
   plan-named acceptance test going green under `bin/test-lock`.) This becomes G1.
2. **Which outcomes need a SEPARATE gate vs. folding into G1?** (Recommended: one gate per independently
   omittable requirement — a lint/typecheck gate, a behaviour gate, a negative-control/mutation gate.)
3. **Is any required outcome impossible to decide by command?** (Recommended: make it runnable if you
   can; only fall back to a manual gate — reviewed by risk — when no command can decide it.)

## Verify

- `claude-template gate-lint <ledger>` → `LINT OK` (no errors).
- `claude-template gate-run status <ledger>` → reports state without executing.
- After a real run: `claude-template gate-run status <ledger>` → `ALL MET` only when every gate is evidenced.

## See also

The executor is a vendored SUBSET of unlazy — only the gate-checker (layers 1+2). unlazy's Depth Tree,
OWNS leases, dispatch waves, and blocking Stop hook were deliberately dropped (they duplicate
worktrees + `parallel_gate`); the rationale + the dropped-layer→native mapping are in
`bin/gate/README.md` ("Why only a subset"), ruled in
`docs/superpowers/specs/2026-08-28-unlazy-gate-ledger-adoption-design.md`. For parallel fan-out of
gate-verified leaves under a node gate, see the `depth-fanout` skill.
