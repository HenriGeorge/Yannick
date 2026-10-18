---
name: ableton-daemon
description: >-
  Check on / start the AbletonOSC gateway daemon (the sole bridge process to Live). Use when Henri
  asks "is Ableton connected?", "is the gateway/daemon running?", "start the daemon", "restart the
  gateway", or a command is failing because the bridge seems down. A thin socket-ping wrapper around
  `python -m sidekick.gateway {status,stop,restart}` — NOT for rack drift/tuning (→ ableton-racks),
  NOT for corpus/sample freshness (→ ableton-library), NOT for the chain-rebalance watcher
  (→ ableton-watch).
---

# Ableton Daemon — gateway lifecycle front door

Wraps `python -m sidekick.gateway {status,stop,restart}` (`sidekick/gateway/__main__.py`) — a thin
CLI around `sidekick.gateway.lifecycle`. Every command probes the daemon's Unix socket directly (a
real liveness check, not a `pgrep`).

## Modes

- **`status`** — read-only. Prints `running (pid <N>)` and exits 0, or `not running` and exits 3.
  Start here for "is Ableton connected?".
- **`restart`** — stops the current daemon (if any) and spawns a fresh one, then reports
  `restarted` (or a failure reason). This is the closest thing to "start the daemon" — there is no
  separate `start` subcommand; a stopped daemon is auto-spawned lazily by the first `connect()` call
  any tool makes (`sidekick/gateway/spawn.py`'s `ensure_daemon_running`), so an explicit `restart` is
  for when Henri wants it up NOW, or suspects it's running stale code after an AbletonOSC fork edit.
- **`stop`** — stops the daemon cleanly. Prints `stopped` or `not-running`.

## Workflow

1. **CHECK FIRST** — always run `status` before assuming anything is broken; a "not running" is
   often not an error (the daemon lazy-spawns on first use).
2. If Henri wants it running NOW, or after editing `vendor/AbletonOSC/` (a fork edit needs a
   restart to take effect — `scripts/sync-abletonosc.sh --reload` is the normal path for CODE
   changes; a full daemon `restart` is for when the daemon PROCESS itself needs to come back, e.g.
   after a crash), run `restart` and confirm the printed status.
3. Never `stop` without Henri asking for it explicitly — a live session may depend on the daemon
   being up.

## Notes

- `--socket`/`--pidfile` override the default paths (`~/.cache/sidekick/abletonosc-gateway.{sock,pid}`)
  — only relevant for a non-standard install; never invent a path.
- This is READ-MOSTLY: `status` never writes anything; `restart`/`stop` only ever affect the daemon
  PROCESS itself, never Live or the `.als`/`.adg` files.
- One client, one daemon: never spawn a second gateway daemon process — the one-client rule
  (CLAUDE.md) means a second AbletonOSC client silently steals the reply stream.
