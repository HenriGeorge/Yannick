# Gates: <plan or task name>

Scope: <one sentence naming the complete deliverable this ledger proves>

<!--
This is an ACCEPTANCE-GATE LEDGER, checked by claude-template gate-check via `claude-template gate-run`.
Name it `<plan-basename>.gates.md` and put it beside the plan in docs/superpowers/plans/.
Reference it from the plan's frontmatter: `gates: docs/superpowers/plans/<plan-basename>.gates.md`.

Rules (see the gates skill):
- One gate per plan checkbox; a runnable gate has BOTH `CHECK:` and `EXPECT:`, a manual gate has neither.
- A gate is MET only when its CHECK exits 0 AND its combined output matches EXPECT. A checked box with
  `EVIDENCE: pending` (or no evidence) is UNMET — never tick a box you have not verified.
- CHECKs may use ONLY canonically-available tools (node, git, coreutils under /usr/bin:/bin, and repo
  `bin/`), because `claude-template gate-run` pins a canonical PATH so a human's arm-time approval stays valid at
  unattended loop-time. Do not rely on tools outside that PATH.
- Make EXPECT a success-ONLY marker your script prints AFTER every assertion passes (not a word that
  failure output could also contain). Measure numbers from source; never copy a briefed figure into EXPECT.
- If a gate becomes genuinely impossible, keep it and add a line at column 1: `ABANDON: G<n> <reason>`.
  Abandonment is a terminal HANDOFF, never success.
-->

- [ ] G1: <observable outcome measured directly from the artifact>
  CHECK: bin/test-lock --wait [--timeout N] -- <your test command; exits 0 and prints the success marker below>
  EXPECT: <a distinctive success-only marker your test prints last>
  EVIDENCE: pending

- [ ] G2: <a second observable outcome, e.g. a lint/typecheck clean run>
  CHECK: <command that exits 0 and prints a distinctive success marker>
  EXPECT: <that success marker>
  EVIDENCE: pending

- [ ] G3: <a manual outcome no command can decide — reviewed by a human>
  EVIDENCE: pending
