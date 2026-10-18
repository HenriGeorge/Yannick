# Gates: test-quality — <plan or PR name>

# HOW TO USE: copy this beside your plan (a COMMITTED, reviewed file — NOT under .unlazy/), fill the
# <placeholders>, then:  bin/test-quality-run <this-file>
# It runs each CHECK through the vendored unlazy executor and prints `<!-- test-quality:PASS@<head> -->`
# ONLY when every gate is met — the marker pr_gate reads at merge (Deliverable L), now earned by a
# real run instead of a judgment. A nonzero CHECK never passes on output-match alone.
#
# Author gates that CAN fail (references/gates.md:93): observe the outcome directly, let the command
# do all the asserting and exit nonzero on any failure, and prove the test can fail (TQ2 below).

- [ ] TQ1: the plan-named acceptance tests are green at HEAD
  CHECK: bin/test-lock -- bash tests/<your-acceptance-test>.sh
  EXPECT: /RESULT: \d+ passed, 0 failed/
  EVIDENCE: pending

- [ ] TQ2: at least one acceptance test is mutation-proven able to fail (the negative control)
  CHECK: bin/mutation-check <covered-source-file> '<sed break, e.g. s/return ok/return bad/>' -- bash tests/<your-acceptance-test>.sh
  EXPECT: mutation-proven: RED
  EVIDENCE: pending

# Optional TQ3: lint THIS ledger so it can't be a fake gate (unlazy gate-lint):
# - [ ] TQ3: this ledger states outcomes that can fail
#   CHECK: node bin/gate/gate-lint.mjs <this-file>
#   EXPECT: LINT OK
#   EVIDENCE: pending
