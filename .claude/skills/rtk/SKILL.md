---
name: rtk
description: Use when a project has RTK enabled (ON by default; opt out with RTK_ENABLE=0 at scaffold), when commands are being prefixed with `rtk`, when a compressed/summarized command output looks wrong or incomplete, or when reasoning about how the `rtk` prefix interacts with the template's PreToolUse guards, telemetry, or project-local `.rtk` filters.
---

# RTK — token-optimized command output (on by default, guard-safe)

> Origin: rules/rtk.md — moved by rules-triage Phase B / plugin phase 2.

RTK ("Rust Token Killer") is a CLI proxy that compresses noisy command output before it
reaches the LLM. This template ships it **ON by default** — `setup.sh` runs `rtk init` on every
scaffold unconditionally (telemetry OFF); set `RTK_ENABLE=0` before setup to opt a project out. Full
doc: `../../docs/RTK.md`; decision: `docs/decisions/feat-rtk-template.md`.

## What to know when RTK is enabled

- **It's instructions, not a hook.** Project-level `rtk init` writes a "prefix commands with `rtk`"
  block into `CLAUDE.md` — it installs **no `PreToolUse` hook** (the real hook is `--global`-only,
  which this template does not do). RTK never sits in the tool-call chain, so it cannot mutate a
  command before the H1–H10 guards inspect it.
- **The safety guards still fire.** RTK's rewrite is additive (`git … → rtk git …`), so the
  template's deterministic guards (force-push to main, destructive DB ops, conventional-commit,
  read-only `rm -rf`, secret scans) still block the `rtk `-prefixed forms. This is pinned by
  `tests/test_rtk_guard_safety.sh` — if you change `pre_tool_use.*`, keep that test green.
- **Telemetry is forced OFF.** The template disables RTK telemetry on enable and never opts a
  downstream project in. Don't re-enable it in a scaffolded project without the user's explicit say.
- **Green ≠ accurate.** RTK summarizes output; a filter can occasionally drop a line you needed. When
  a compressed result looks wrong, re-run the command raw (no `rtk ` prefix) to compare. Never trust
  project-local `.rtk` filters from a repo you don't control (`rtk trust` is the gate; avoid
  `--trust-filters`).

## See also

`../../docs/RTK.md` (setup/enable/disable, mechanism, caveats) · `engineering-conventions.md` (R5 — RTK's
dependency cost is why telemetry stays OFF and the guards must still fire even now that it defaults ON) · `hooks/README.md` (the PreToolUse guard chain RTK
must not defeat) · `workflow.md` (GATE 2 — "green ≠ works" applies to RTK's compressed output too).
