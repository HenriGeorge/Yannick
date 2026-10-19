---
name: ableton-watch
description: >-
  Check on / configure the always-on chain-rebalance-on-save watcher (RackSaveWatch — auto-rebalances
  a role rack's chain-selector zones when its canonical .adg is re-saved, and hot-reloads it into Live
  for allow-listed roles). Use when Henri asks "is the rebalance watcher running?", "what did the
  watcher just do?", "any nudges from the watcher?", "allow-list this role for auto-reload", or "stop
  auto-rebalancing this rack". Wraps `scripts/rack-watch.py` (status + allow-list) — NOT the gateway
  daemon PROCESS itself (→ ableton-daemon), NOT rack drift/tuning/snapshots (→ ableton-racks, the
  offline sweep — RackSaveWatch is the LIVE, always-on save-triggered watcher, a different concern).
  Enabling/disabling the watcher is the daemon's own env-gated flag (default OFF), not a script this
  skill drives interactively — see Modes below.
---

# Ableton Watch — RackSaveWatch (rebalance-on-save) front door

Wraps `scripts/rack-watch.py` — `status` (query the running watcher over the daemon's Unix socket)
and `allow-list` (inspect/add/remove which roles get full auto). Read-only + pure-file-I/O only:
this skill never triggers a rebalance or reload itself — those happen automatically, in the daemon's
own background thread, whenever an allow-listed role's canonical `.adg` is re-saved in Live.

## Modes

- **`status`** — `python3 scripts/rack-watch.py status`: prints whether the watcher's background
  thread is running, which roles are currently allow-listed, and its most recent nudges (the
  human-facing safety-net messages — rebalanced+reloaded confirmations, deferred-reload reasons,
  post-reload mismatch alerts). Start here for "what's the watcher up to?" or "did my save trigger a
  reload?". Queries the daemon's `rack_save_watch_status` request kind over its Unix socket — this
  is the SAFE, socket-only path; it deliberately never falls back to constructing a raw OSC
  transport.
- **`allow-list list`** — prints the currently allow-listed roles (full auto: in-place rebalance +
  live reload). Any role NOT listed only ever gets Level 1 (a non-destructive `racks/` history
  snapshot + a nudge) on a re-save — never an in-place write, never a reload. **DEFAULT = ALL roles**
  (Henri, 2026-08-08 — "watcher on all tracks"): a never-armed / reset allow-list (absent file)
  watches every role rack; the list narrows only when you explicitly `remove` (or `save`) a set.
- **`allow-list add <role>`** / **`allow-list remove <role>`** — opts a role_key (e.g. `bass`,
  `lead`, `keys`, `pads`, `texture`) into/out of full auto, narrowing FROM the default-all. Pure
  JSON file edit (`~/.cache/sidekick/rack_save_watch_allowlist.json`) — takes effect on the
  WATCHER's next poll round (default every 1s; `SIDEKICK_RACK_SAVE_WATCH_POLL` overrides), no daemon restart needed. An explicitly-saved EMPTY
  list means "watch nothing" and is respected (the default only re-expands to all when the file is
  ABSENT, never when it's a saved-empty). **Aesthetic/behavioral opt-in, not a Live write** — never
  touches a `.adg` or Live itself.
- **Enable/disable the watcher itself is NOT a subcommand here** — it's the daemon's own env-gated
  flag, default OFF: `SIDEKICK_RACK_SAVE_WATCH=1 python -m sidekick.gateway restart` to enable, a
  plain `python -m sidekick.gateway restart` (no env var) to disable. Route THAT specific action
  through `ableton-daemon` (the daemon-process skill) since it's a daemon restart, not a new
  mechanism this skill wraps.

## ChainWatch — the live-chain-count nudge sibling (2026-09-18)

`status` also prints a **`chain-watch`** section. ChainWatch is a SEPARATE background watcher (design:
`docs/superpowers/specs/2026-09-18-chain-watch-design.md`) that catches an engine-chain add/delete in a
role rack **while you're editing in Live** — before a save. It is **nudge-only**: it can't do the recalc
itself (chain-selector zones aren't live-writable on 12.3.2, and a live-added chain isn't in the `.adg`
until ⌘S — both LOM walls). So it prints e.g. `Sub Rack: live engine chains 5→6 — ⌘S to rebalance zones`,
telling you a save is due the moment the count changes, instead of you finding out on the next save. The
actual rebalance is still RackSaveWatch's job once you save.

- **Dedicated channel.** ChainWatch polls READ-ONLY on its OWN AbletonOSC instance (default 2 =
  11002/11003), a separate reply stream — zero contention with the crew channel on 11000/11001, and not a
  one-client-rule violation (that rule guards 11001). Needs the AbletonOSC2 instance synced+running
  (`scripts/sync-abletonosc.sh --instance=2` + the AbletonOSC2 control surface in Live); if it's absent,
  ChainWatch logs one loud fix-naming nudge and idles (never crashes the daemon).
- **Env-gated, DEFAULT ON.** Opt out `SIDEKICK_RACK_CHAIN_WATCH=0`; poll cadence
  `SIDEKICK_RACK_CHAIN_WATCH_INTERVAL` (default 4.0s, floored 1.0); instance
  `SIDEKICK_RACK_CHAIN_WATCH_INSTANCE` (default 2, validated 2..4 — never instance 1). Same daemon
  restart as RackSaveWatch to (re)load it.
- **Read-only + nudge-only** — never writes Live, never an `.adg`, never touches the allow-list; the
  allow-list gates RackSaveWatch's auto-write/reload, not ChainWatch.

## Workflow

1. **CHECK STATUS FIRST** — `status` before assuming anything did or didn't happen; the watcher
   only acts a couple seconds after a save lands (poll 1s + quiescence window 1.5s default ≈ ~2.5s
   worst case; `SIDEKICK_RACK_SAVE_WATCH_QUIESCENCE` overrides, floored at 0.5s — a save-then-
   immediately-check may show nothing yet).
2. **Allow-listing is the gate for auto-write/reload** — a role must be explicitly added before its
   re-saves get anything beyond a passive snapshot+nudge. Never add a role to the allow-list without
   Henri asking — it's the difference between "safe observe-only" and "auto-overwrites + auto-
   reloads the live rack."
3. **Reading nudges is how you learn what happened** — the watcher never blocks or prompts; every
   outcome (rebalanced, deferred because Live was playing, skipped because a save didn't capture an
   engine, a post-reload mismatch) is a nudge in `status`'s output. If something seems off after a
   save, `status` first, before assuming a bug.

## The reload leg works automatically — no manual precondition to check

The guarded reload does NOT require you to babysit anything before it fires. `sidekick.connect()`'s
own dispatch order ALWAYS returns a `GatewayTransport` over the daemon's Unix socket while the daemon
is healthy — its raw-`UdpTransport` SOLO fallback (which would bind UDP 11001) only fires when the
daemon itself doesn't answer a ping, or a caller explicitly passes `use_gateway=False`. So in real
always-on operation the daemon is automatically the sole OSC client, and AbletonOSC's fixed-port
replies always reach it — this is a guarantee of the architecture, not a "check `lsof` first" ritual.
The one residual case — a manually-run `use_gateway=False` script briefly overlapping a reload —
self-heals on its own: the pre-reload track-names read retries a bounded number of times with a short
backoff before giving up, and that window is almost always enough for a transient stray binder's
socket to close. Only if every retry is exhausted does the existing fail-safe fire (a nudge, reload
skipped, will retry next round — never a false rollback claim). Running an explicit SOLO client
alongside the daemon is simply unsupported; you don't need to check for it before normal use.

## Notes

- The watcher is COUNT-based for its engine-chain "identity" check (pre/post reload), not per-
  device-class — documented, deliberately-scoped Wave-1 gap (see `sidekick/gateway/
  rack_save_watch.py`'s own module docstring). A same-count device SUBSTITUTION is not caught; a
  count MISMATCH (the "save didn't capture the added engine" scenario) is.
- The reload is an IN-PLACE HOT-SWAP (`sidekick.librarian.rack_hotreload`, 2026-08-10 design,
  #171 — replaces the earlier probe-gated delete-then-load). A live de-risk proved a DIFFERENT load
  path than plain `load_browser_item`: `load_on_nested_device` with `path=[]` sets Ableton's native
  `Browser.hotswap_target` to the TOP-LEVEL device and loads INTO it — this REPLACES an OCCUPIED,
  engine-baked role rack in place, no delete, no scratch track, no empty-track requirement. So the
  watcher copies the canonical to a fresh-unique temp (`"<name> (reloading <token>).adg"`, a uuid
  token — a name the device could never already show), hot-swaps that temp DIRECTLY onto the live
  device, then reads the device's name back: seeing it become the temp's stem is the proof the swap
  LANDED (the side-car's own reply is never trusted — it reports success even on a silent no-op). A
  landed swap gets renamed back to canonical (verify by count, force the name); the temp is ALWAYS
  cleaned up. If no name transition is observed after several attempts (stuck browser, stale cache,
  or a transient hiccup — all handled identically) it SKIPS — the real rack is UNCHANGED (nothing
  was ever deleted, so there's nothing to orphan), reported as the same `COULD-NOT-RELOAD` nudge
  (drag the preset in / restart Live). The `ORPHANED` nudge from the old delete-based design is
  retired — structurally impossible now; a name-force failure after a good swap is still a distinct
  `NAME-NOT-CANONICAL` nudge (the swapped content IS on the track — just rename by hand). A
  companion ableton-mcp Remote-Script fix makes the LOAD path re-walk the browser fresh (backing the
  fresh-URI approach) — **it needs a Live restart to deploy**. The `_version_N.adg` SAFETY
  BACKUP (a restore point, made before any in-place write) is a completely separate, unaffected
  mechanism — and it lives at `~/.cache/sidekick/rack-backups/<RackName>/`, NOT beside
  the canonical User-Library preset, so it never shows up as a selectable preset in Ableton's own
  browser. Full history: `docs/decisions/feat-rack-save-watch.md` §E.
- Never edit `role_specs.py`/the `.adg` files based on anything this skill shows — it's purely
  observational (status) or a policy toggle (allow-list); the actual rebalance/reload logic lives
  entirely in the daemon's background thread.
- The allow-list fails **OPEN** to all-roles on an absent, unreadable, or corrupt file (loudly
  logged) — the ONLY way to get a narrower or empty set is an explicit `save()`/`remove` that writes
  a real `roles` list to disk. An explicitly-saved empty list means "watch nothing" and is respected
  verbatim.
