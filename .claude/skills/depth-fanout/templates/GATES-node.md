# Gates: <branch/integration name>

Scope: integrate children <child leaf ids> into one command-verified result.

<!--
NODE (parent) gate — run AFTER all children return and BEFORE worktree teardown.
Drive with claude-template gate-run (arm once, verify in the loop). See the depth-fanout skill.
N1 is mandatory: reverify EVERY child from its exact ledger (green leaves can rot by integration).
N2 must exercise the cross-child surface no single leaf owns — a node gate without a real N2 is under-specified.
Replace every placeholder before arming — the `<...>` fields in the heading/Scope, the `LEAF-*.gates.md`
paths in N1, and the `REPLACE-WITH-*` stubs in N2/N3; the CHECK/EXPECT below are parseable stubs, not real commands.
Example N1 CHECK: claude-template fanout-status ../leaf-a/g.gates.md ../leaf-b/g.gates.md
-->

- [ ] N1: every named child leaf reverifies green
  CHECK: claude-template fanout-status LEAF-A.gates.md LEAF-B.gates.md
  EXPECT: READY TO INTEGRATE
  EVIDENCE: pending

- [ ] N2: the cross-child behaviour works end to end
  CHECK: REPLACE-WITH-command-exercising-the-integrated-surface
  EXPECT: REPLACE-WITH-success-only-marker
  EVIDENCE: pending

- [ ] N3: the full suite still passes (nothing regressed)
  CHECK: bin/test-lock --wait [--timeout N] -- REPLACE-WITH-full-test-command
  EXPECT: REPLACE-WITH-success-marker
  EVIDENCE: pending
