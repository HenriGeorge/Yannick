---
name: model-routing-audit
description: Use when auditing a repo (or a fleet of repos) for bare model aliases (sonnet/opus/haiku/fable) in agent/skill frontmatter or --model flags — an alias floats to the newest generation. Triggers on "audit model routing", "are we pinning model ids", scanning agents/skills for a floating model.
---

# model-routing-audit

## Overview

Bare model aliases (`sonnet`/`opus`/`haiku`/`fable`) float to the newest generation. Policy is to
**pin an exact ID** (see the routing table in `rules/agent-delegation.md`) — any explicit, dated or
versioned id (`claude-opus-4-8`, `claude-haiku-4-5-20251001`, `claude-opus-5-5`) is clean; only the
bare alias leaks. This skill runs a deterministic scan for the two **statically detectable** leak
surfaces and leaves the judgment (is a finding intentional? which id is right?) to you.

## When to use

- Before a merge/release, or when adding/editing agent or skill frontmatter.
- Auditing a **fleet**: run `scan.py --root <each repo>` across repos.
- You suspect an agent/script is silently on a floating alias.

## Run it

```bash
python3 skills/model-routing-audit/scripts/scan.py            # scan cwd, human table
python3 skills/model-routing-audit/scripts/scan.py --root ~/Projects/foo --json
```

Exit **1** if any leak is found (so it doubles as a CI/pre-merge gate), **0** if clean.

## What it flags (static only)

| Surface | Example (flagged) | Not flagged |
|---|---|---|
| `model:` assignment | `model: sonnet` | `model: claude-opus-4-8`, `model: claude-haiku-4-5-20251001`, `model: claude-opus-5-5` |
| `--model` flag | `--model opus` | `--model claude-opus-4-8` |

It inspects only real `model:` / `--model` **assignments** — a prose mention of the alias words is
**not** a false positive. Only a BARE alias leaks; any explicit model id (of any generation) is clean.
Patterns are kept in lockstep with `tests/test_model_routing.sh` (MR-01/MR-02).

## Boundary — the third leak surface this CANNOT see (now covered by hook H11)

There are **three** floating-alias leak surfaces (rules/agent-delegation.md): frontmatter `model:`,
`--model` flags, and the **runtime Agent/Task-tool `model:` parameter**. The first two are static
strings in files — this scanner covers them. The **runtime param is not a static string anywhere**,
so no file scan can detect it — it needs a PreToolUse hook.

That hook now **exists**: **H11 Agent/Task model-guard** (`hooks/pre_tool_use.py` +
`hooks/node/pre_tool_use.cjs`, shipped in #179 — see `hooks/README.md`) hard-blocks a subagent
dispatch whose `model:` param is a bare alias. So the three surfaces are now
jointly covered: **this skill (static files) + H11 (runtime dispatch)**.

**A clean scan here still does NOT prove the runtime param is safe** — that's H11's job, and H11 only
fires where `pre_tool_use.py` is registered in `.claude/settings.json` (a repo that hasn't wired the
hook is unguarded at runtime). The safe form remains: OMIT the `model:` param on a dispatch and let
the agent def's pinned id win.

## Gotchas

- **Exit 1 ≠ broken build** — it means leaks were found; read them, then fix (pin an exact id) or
  confirm each is intentional.
- **Scope is files, not runtime** — see the Boundary section. Don't report "model routing is clean"
  on a green scan alone; say "static surfaces clean; runtime param unaudited".
- **Fleet runs**: a repo with its own vendored `plugins/` cache is skipped (that's not your code).
- **Precision trade-off (known false-negatives):** `model:` is read only inside a file's LEADING
  frontmatter block, and `--model` only in script files — deliberately, so docs/tables/tests that
  MENTION an alias aren't false positives. The cost: a `model:` set OUTSIDE frontmatter (a nested
  YAML key, a `"model": "opus"` in `settings.json`) is NOT caught by this scan. In the claude_template
  repo itself, `tests/test_model_routing.sh` MR-09 guards the tracked `.claude/settings*.json`
  `model` key. In other repos, grep by hand (`grep -rn '"model"' .claude/settings*.json`). `--model` values may be quoted (`--model "opus"`) —
  those ARE caught; a shell-expansion value (`--model "$VAR"`) is intentionally not.
