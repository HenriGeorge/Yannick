---
name: rtk
description: Use when a project has RTK enabled (always on — no opt-out, #1410), when commands are being prefixed with `rtk`, when a compressed/summarized command output looks wrong or incomplete, or when reasoning about how the `rtk` prefix interacts with the template's PreToolUse guards, telemetry, or project-local `.rtk` filters.
---

# RTK — token-optimized command output (on by default, guard-safe)

> Origin: rules/rtk.md — moved by rules-triage Phase B / plugin phase 2.

RTK ("Rust Token Killer") is a CLI proxy that compresses noisy command output before it
reaches the LLM. This template ships it **ON by default** — `setup.sh` runs `rtk init` on every
scaffold unconditionally (telemetry OFF); always on, no opt-out (#1410 — a per-repo opt-out was
cosmetic, since the mechanism it would have disabled was machine-global, not project-local). Full
doc: `../../docs/RTK.md`; decision: `docs/decisions/feat-rtk-template.md`.

## What to know when RTK is enabled

- **It's a template-authored plugin hook, not rtk's own global one.** `plugins/ct-hooks-py/hooks/
  rtk_rewrite.py` (PreToolUse, matcher `Bash`) replaced rtk's own `rtk init -g` global hook — that
  global form patched the MACHINE-GLOBAL `~/.claude/settings.json` and couldn't work in a claude.ai
  cloud session (no persistent machine-global config there). The plugin hook ships WITH the
  project, excludes `git` itself (so a worktree-isolated `git` is never rewritten, #709), and
  delegates the actual rewrite to `rtk hook claude` for everything else.
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
