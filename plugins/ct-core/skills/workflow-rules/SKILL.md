---
name: workflow-rules
description: The canonical claude_template development workflow — the two laws (Design → Code → Prove), the 9 phases, the two hard gates, autonomy, engineering conventions, agent delegation, the design and verify pipelines, and the doc/output conventions. Use when working in a repo scaffolded from claude_template, when asked how the workflow / gates / phases work, when orienting to "how we work here", or before starting design or implementation in such a project. Each rule's full text is in references/ — read the one the question needs.
---

# claude_template workflow rules

The canonical workflow every claude_template project follows. **The two laws override everything:**

1. **Design before code (GATE 1)** — no implementation until an approved design exists.
2. **Evidence before "done" (GATE 2)** — never claim done/fixed/passing without fresh output this turn.

The full rule text lives in `references/`. Read the file the current question actually needs —
don't load all nine unless you must.

| Rule | `references/` file | What it covers |
|------|--------------------|----------------|
| Canonical workflow | `workflow.md` | GATE 0/1/2, the 9 phases, test cadence, worktrees + merge queue — **start here** |
| Autonomy | `autonomy.md` | Decide by default; stop only for a genuine blocker; batch questions |
| Engineering conventions | `engineering-conventions.md` | R4–R10: prefer editing over creating, justify deps, security basics, Ponytail, git hygiene, comments |
| Agent delegation | `agent-delegation.md` | When/how to delegate; the risk-tiered review panel; model routing |
| Lean output | `lean-output.md` | Default to concise; evidence always wins over brevity |
| Mermaid conventions | `mermaid-conventions.md` | Diagram flows/state/architecture inline over prose or stale images |
| Design workflow | `design-workflow.md` | The *how* of GATE 1 — SHAPE → PRESSURE-TEST → MAKE CONCRETE → COVER |
| Verify workflow | `verify-workflow.md` | The *how* of GATE 2 — STATIC → BEHAVIORAL → EXERCISE → CLAIM |
| Doc conventions | `doc-conventions.md` | D1–D4: `Last updated:` stamps, `@`-import discipline, plugin vs maintainer docs |

> In a local repo/fleet session only the 4 every-turn rules (`workflow`, `engineering-conventions`,
> `autonomy`, `lean-output`) load natively via `CLAUDE.md`'s `@.claude/rules/*.md` imports; the other
> 5 (`agent-delegation`, `verify-workflow`, `design-workflow`, `doc-conventions`,
> `mermaid-conventions`) are read on demand from `.claude/rules/` at the gate `workflow.md` names (the
> @-import loading diet). This skill is the cloud-session channel for all nine, where the imports and
> the `.claude/rules/` directory aren't present.
