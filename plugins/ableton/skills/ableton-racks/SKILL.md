---
name: ableton-racks
description: >-
  Check the Performance Rack roles (Bass/Lead/Keys/Pads/Texture) for config-drift, User-Library
  freshness, and unsaved live tuning; snapshot a rack `.adg` into versioned history. Use when Henri
  says "check racks", "check the racks now", "is there rack drift?", "snapshot this rack", "has this
  rack been resaved?", or "did I forget to commit a tuning change?". Consolidates
  `scripts/check-racks.py` (one-shot read-only sweep + `--tuning` live sub-mode) and
  `scripts/rack-snapshot.py` (versioned snapshot) — NOT for the daemon process itself
  (→ ableton-daemon), NOT for sample/preset corpus freshness (→ ableton-library), NOT for the
  chain-rebalance watcher (→ ableton-watch). This skill DRIVES
  the read-only/`--no-apply` sweep and PRESENTS what check-racks.py offers — it never auto-answers
  an interactive y/N prompt on Henri's behalf.
---

# Ableton Racks — drift sweep + versioned snapshots

Two scripts, two distinct jobs. Both are strictly read-only toward the canonical `.adg` unless
Henri explicitly confirms a write (`racks/` history writes are non-destructive; a config-drift
`--write` or an in-place rebalance is a SEPARATE explicit 'y' each time, per `check-racks.py`'s own
consent contract — never auto-answered by this skill).

## A. `scripts/check-racks.py` — the drift sweep

Default (no flags): every role's config-drift + User-Library freshness + macro-inheritance warnings,
as a summary table. This is the front door — start here for "check racks now".

- **Read-only default:** `python3 scripts/check-racks.py --no-apply` — table + per-role detail,
  zero interactive prompts. Use this for a quick health check Henri didn't ask to act on yet.
- **Interactive (default, no `--no-apply`):** surfaces two offer chains (NEW-SAVE
  snapshot-then-config-capture; CONFIG-DRIFT `--write`) as `[y/N]` prompts — PRESENT these to Henri
  verbatim and relay his answer; never decide for him.
- **`--role <Name>`** narrows to one role.
- **`--tuning`** (needs the daemon/Live up) — a SEPARATE, exclusive, live-only mode: reads each
  loaded role rack's baked engine params NOW and diffs against its latest snapshot baseline,
  catching UNSAVED tuning the offline sweep can't see (Live has no save API). Report-only — never
  writes; names the save-then-snapshot command for Henri to run by hand.
- **`--hot-reload`/`--watch`** exist but belong to the RackSaveWatch feature (feat/rack-save-watch)
  — don't drive these from this skill; that's `ableton-watch`'s job.

Exit codes: 0 clean · 1 informational (NEW-SAVE/NO-USERLIB/NO-HISTORY) · 2 actionable
(CONFIG-DRIFT/ERROR) · 3 the tool itself crashed.

## B. `scripts/rack-snapshot.py` — versioned history capture

For a SPECIFIC rack `.adg` Henri names (not a sweep — this takes one path):

    python3 scripts/rack-snapshot.py "<rack.adg>"                       # snapshot it
    python3 scripts/rack-snapshot.py "<rack.adg>" --label v5 --note "…" # with annotations
    python3 scripts/rack-snapshot.py "<rack.adg>" --check               # drift check, writes nothing

Strictly read-only toward the canonical `.adg` (md5-verified before/after); writes only into
`racks/` history. `--check` never writes anything — use it to ask "has this rack drifted from its
last snapshot?" without capturing a new one.

## Workflow

1. **SWEEP FIRST** — `--no-apply` for a quick read, or the interactive default if Henri wants to
   act on findings right now.
2. **PRESENT, don't decide** — relay each `[y/N]` offer verbatim; only proceed on Henri's explicit
   answer.
3. For a one-off "snapshot this rack" request naming a specific file, use `rack-snapshot.py`
   directly rather than the sweep.
4. `--tuning` only when Live is actually up and Henri wants to know about UNSAVED changes.

## Notes

- Neither script ever writes a canonical `.adg` — "Ableton owns the racks" (CLAUDE.md/racks.md).
  The only writable surfaces are `racks/` history and, on an explicit CONFIG-DRIFT 'y',
  `role_specs.py`'s marker-delimited override block.
- `--db-path`/`--racks-root`/`--userlib-root` override defaults for testing only — never point
  these at a non-default location without Henri asking.
