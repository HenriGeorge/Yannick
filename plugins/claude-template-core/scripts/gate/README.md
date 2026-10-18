# bin/gate — vendored machine-checked gate executor

Last updated: 2026-10-17 12:47

Vendored subset of **unlazy** (`unlazy-skill` v2.1.0, https://github.com/Leonxlnx/unlazy) — a
zero-dependency Node completion-gate checker. We use ONLY the executor (layers 1+2): a gate ledger
declares `- [ ] ID: outcome` + `CHECK:` (shell) + `EXPECT:` (text/`/regex/`) + `EVIDENCE:`, and
`gate-check.mjs` **executes** the CHECK, passing a gate only when the process exits `0` AND `EXPECT`
matches combined stdout+stderr. A nonzero process never passes on token-match alone — the anti-theater
property that makes a "green" un-fakeable.

## Why only a subset (see the design spec's grill ruling)

`docs/superpowers/specs/2026-08-28-unlazy-gate-ledger-adoption-design.md` re-scoped adoption to layers
1+2 after an adversarial grill. We **dropped** unlazy's orchestration layers (the blocking Stop hook,
the leaf/branch tree, OWNS leases, dispatch, and the standalone `install-hooks.mjs`) because they
duplicate the repo's existing orchestration (native worktrees + `parallel_gate` + crew-coordinator +
`bin/test-lock`) and break in CI/unattended (the `--approve` identity binds cwd+shell+PATH). This dir
is a **producer toolchain** invoked by the test-quality path — it is NOT a Stop hook and never
force-runs. It injects no runtime dependency into the Python hook layer.

### Dropped layer → native equivalent

Every orchestration layer we dropped is already covered by a native mechanism — this mapping is why
re-adding them would only duplicate what the repo has (do NOT port them back):

| unlazy layer (dropped) | native equivalent |
|--|--|
| Depth Tree (leaf/branch decomposition) | the `depth-fanout` skill — per-leaf `gates-leaf.md` + a node gate from `templates/GATES-node.md` |
| OWNS ownership leases | git worktrees (real write-isolation, one writer each) + `parallel_gate` (disjoint-file enforcement at plan-commit) |
| dispatch waves (open/start/seal/return barrier) | "launch the whole batch in ONE message" concurrency barrier + `claude-template fanout-status` readiness oracle |
| blocking Stop hook + `install-hooks.mjs` | attended `claude-template gate-run verify` on a plan's `gates:` ledger, integrated with `pr_gate` |

Note unlazy's leases/waves are coordination-only (NOT write-isolation); worktrees + `parallel_gate`
give stronger guarantees than the layers they replace.

## Vendored files (verbatim, no fork patches)

- `gate-check.mjs` — the executor (`--approve` / `--status` / `--reverify`)
- `gate-lint.mjs` — lexical fake-gate linter (never executes a CHECK)
- `lib/gates.mjs` · `lib/process-tree.mjs` · `lib/dispatch.mjs` · `lib/check-supervisor.mjs` ·
  `lib/regex-worker.mjs` — the executor's real import graph (`dispatch.mjs` is a transitive dep of
  `gate-check`; its pipeline/tree features are unused here)

Dropped from upstream: `scripts/stop-hook.mjs`, `scripts/install-hooks.mjs`, `scripts/dispatch-check.mjs`,
`templates/`, `references/`.

## Honest limits (from the grill)

- **Not a CI oracle.** `--approve` keys to exact CHECK/EXPECT/cwd/shell/PATH stored per-machine under
  `~/.unlazy/approved` — approvals don't transfer to CI. Gates are a **dev-machine + pre-merge
  producer**; the `test-quality:PASS@head` PR marker is emitted from a real local run, and `pr_gate`
  gates the merge on that marker (as Deliverable L already does).
- **`--approve` is accident-defense, not a security boundary** against a determined agent with Bash.
- **Node ≥16 required.** The producer wrapper detects a too-old/missing node and fails VISIBLY — it
  must never silently pass.

## Re-vendor checklist (M7 — no upstream auto-sync)

Vendored from unlazy-skill **v2.1.0**. To update: re-copy the 7 files above from the upstream
`scripts/`, re-run `bash tests/test_gate_executor.sh`, diff for any new import, and bump this version
line. Do NOT hand-edit the vendored `.mjs` (keeps re-vendor a clean copy).
