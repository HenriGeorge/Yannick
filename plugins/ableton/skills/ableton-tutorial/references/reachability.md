# 12.3.2 reachability table + premake entry points

Canonical routing reference for step 2 (ROUTE) of the ableton-tutorial workflow. Live is
**12.3.2** (verified on disk, `2025-12-15_bba1e05a87`).

**This table was rewritten 2026-07-22.** The previous version was pinned to 12.2.5 and declared rack
construction, macro mapping, chain zones, automation drawing and saving as _permanently_ MANUAL.
Five of those rows were wrong — the version moved, and this repo shipped capability that routes
around the LOM entirely. Treating a stale MANUAL as permanent silently suppresses real capability, so
**every MANUAL row below now carries the evidence for why it is one.**

Three reachability tiers, not two:

- **AUTO-OFFLINE** — the artifact is a **file**, built by `sidekick/racksmith` (`.adg` gzipped XML)
  and written straight to disk. No LOM and no save verb — but **a write into Ableton's User Library
  DOES need Live** (see the save row: it is default-refused without a liveness check). Covers macro maps, chain zones,
  variations, colours, and param values **on devices that already exist in the rack**.
  **It cannot add devices.** `compile_recipe` says so itself — _"this compiler wires structure, it
  never invents sound"_ (`racksmith/recipes/__init__.py:171-173`); there is no insert/add/create
  device transform anywhere in `racksmith/`. Getting the devices IN is a separate, **already-shipped**
  step — `load_into_rack_chain` (side-car + `Song.move_device`), not a racksmith transform.
- **AUTO-LOM** — a property/param write on the **running** set via AbletonOSC.
- **MANUAL** — genuinely out of reach: a third-party plugin with no stock equivalent, or a judgement
  only ears can make.

## Routing table

| Tutorial-technique class                                          | Verdict                       | Mechanism                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------------------------------------------------------- | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tempo / global song settings                                      | AUTO                          | `song.tempo` RW                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Arrangement markers / cue points                                  | AUTO                          | `song/cue_point/add_or_delete` + `set/name`                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| Track creation (audio/MIDI/return)                                | AUTO                          | `song.create_audio_track` / `create_midi_track` / `create_return_track`                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Track naming (incl. emoji)                                        | AUTO                          | `track.name` RW — classify on the state change (a name string), not the UI gesture                                                                                                                                                                                                                                                                                                                                                                                                                             |
| Track routing (input/output type + channel)                       | AUTO                          | `track get/set output_routing_type/channel`, `input_routing_type/channel` + `available_*` enumerators. **String-matched setters fail SILENTLY on mismatch — always read back to verify**                                                                                                                                                                                                                                                                                                                       |
| Track volume / pan / mixer values                                 | AUTO                          | `_get/_set_mixer_property`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| Sends (per-send level)                                            | AUTO (once the return exists) | `track get/set send`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Param value on an ALREADY-LOADED device (incl. macro knob VALUES) | AUTO                          | `SidekickClient.set_device_parameter` → `/live/device/set/parameter/value`; resolve param BY NAME via bulk name-list read; verify by read-back w/ relative tolerance                                                                                                                                                                                                                                                                                                                                           |
| Composition content (chord voicings, drum patterns)               | AUTO (different path)         | Match the indexed MIDI library → `stage_chords` / `stage_drums` (Slice B). A LOOKUP, not generation                                                                                                                                                                                                                                                                                                                                                                                                            |
| Load a single stock device / preset onto a track                  | HYBRID                        | side-car `load_browser_item`, URIs `query:Synths#<Name>` / `query:AudioFx#<Name>`; re-verify via real AbletonOSC device-count read, never the side-car "success" alone                                                                                                                                                                                                                                                                                                                                         |
| Devices INTO an existing rack chain                                | **AUTO — shipped & live-verified** | `load_into_rack_chain(...)` (`sidekick/librarian/rack_chain_stage.py:215`): side-car loads onto a scratch track → `Song.move_device` into `rack.chains[i]` → verifies the chain grew by 1, prior devices untouched, scratch emptied. Raises on any mismatch, never silent. Nested racks: side-car **`load_on_nested_device`** via `Browser.hotswap_target`. Full guide + gotchas: `docs/guides/LOAD-INTO-RACK-CHAIN-HOWTO.md`. **This is the device-insertion path — do NOT wait on `Chain.insert_device`.** |
| A NEW chain in a rack                                              | **AUTO — LIVE-PROVEN 2026-07-22** | `/live/device/insert_chain` (`vendor/AbletonOSC/abletonosc/device.py:339`) → `("ok", before, after)`. `/live/device/probe_construction` on Henri's real set returned **`device:insert_chain`, `chain:insert_device`** on BOTH the outer rack and the nested ENGINES rack (path `1,0,1`). The long-standing "chain creation is hand-drag only" wall is **DEAD**. *(`delete_chain` did NOT probe present — removal is still manual.)* |
| Macros (add / map / name / colour)                                 | **AUTO**                      | Map+name+colour offline via racksmith (`semantic_macros.py:70`). `RackDevice.add_macro` is also present in 12.3.2's LomTypes (no OSC handler wired). |
| Parameters on a device INSIDE a rack chain                         | **AUTO — LIVE-PROVEN 2026-07-22** | `SidekickClient.set_nested_parameter(track, device, name_or_index, value, path=((chain, dev),))` over `/live/device/set/nested/parameter/value` (`device.py:230-315`). Resolve **by name** — indices shift between Live versions. `get_nested_parameter` returns `(name, value, min, max, display)`; **always read `display`** — ranges are routinely normalized `[0,1]` behind a Hz/dB/% name (Auto Filter `Frequency` is `[0,1]` meaning 20 Hz–20 kHz, exponential). `get_nested_parameter_labels` enumerates an enum (`{0 Low-pass, 1 High-pass, 2 Band-pass, …}`) so you never guess one. The setter refuses out-of-range rather than letting Live clamp, and verifies from Live's read-back. |
| A device's ROUTING (e.g. Compressor sidechain SOURCE)              | **MANUAL**                    | Not in the LOM: the Device class exposes only `can_have_chains, can_have_drum_pads, class_display_name, class_name, is_active, latency_in_ms, type, view`. `input_routing_*` belongs to Track/Chain, never Device. Set the sidechain source by hand; `S/C On` and every other sidechain *parameter* ARE reachable. |
| Macro mapping (param → macro knob)                                | **AUTO-OFFLINE**              | `racksmith/transforms/semantic_macros.py:70` `add_mapping(param_el, macro_index, lo, hi)`; `permute_macro_families:20`. No LOM function exists — the `.adg` is the way                                                                                                                                                                                                                                                                                                                                         |
| Chain-select zones / crossfades                                   | **AUTO-OFFLINE**              | `racksmith/transforms/selector.py:34` `set_zones(...)`, `palette_walk_zones:13`                                                                                                                                                                                                                                                                                                                                                                                                                                |
| Saving a `.adg` (rack / preset)                                    | **AUTO-OFFLINE, guarded**     | Anywhere EXCEPT the User Library: `Adg.save_validated(path)` writes the gzipped XML directly. **Into `~/Music/Ableton/User Library`: use `guarded_save(adg, path, client)`** (`sidekick/racksmith/live_sync.py:130`) — `Adg.save()` **default-REFUSES** an unchecked User-Library write (`LiveHoldsRackError`). Live keeps a loaded rack in memory and never re-reads the file, so an unchecked write is silently reverted by Live's next preset-save — a real 2026-07-22 incident that cost five settings **and reported CLEAN**. The guard needs a live `client`, so this path is NOT Live-free. |
| Saving the `.als` (the SET)                                       | HYBRID (GUI)                  | Still no API. Driven by Accessibility keystroke injection (`cliclick` + `screencapture` to verify) — see CLAUDE.md. **Confirm the file on disk (path + mtime) before claiming a save**; a dismissed dialog is not proof                                                                                                                                                                                                                                                                                        |
| Automation-envelope drawing                                       | **AUTO-LOM**                  | `/live/clip/create_automation` — `vendor/AbletonOSC/abletonosc/clip.py:174-237` (LOCAL FORK). **Proven live:** first call returned `created=1` with breakpoints written (`docs/decisions/automation-scripts-research.md:75`). The old "`Clip` has `clear_envelope`, never `create`" claim was false                                                                                                                                                                                                            |
| Spring reverb                                                     | **MANUAL**                    | No native stock device — Hybrid/Convolution Reverb approximates. A genuine gap, not a wiring gap                                                                                                                                                                                                                                                                                                                                                                                                               |
| Any third-party plugin with no stock equivalent                   | **MANUAL**                    | The only remaining hard class. Prefer a stock mapping where the guide already supplies one                                                                                                                                                                                                                                                                                                                                                                                                                     |
| An ear judgement (does it sound right / sit in the mix)           | **MANUAL**                    | Never claim it. Structure is proven by read-back; truth by listening                                                                                                                                                                                                                                                                                                                                                                                                                                           |

Note: "automate a param WHILE recording the print" is a scripted real-time `set_device_parameter`
sweep (AUTO-LOM), NOT a clip automation envelope — read the intent, not the word "automation". Both
are now reachable, but they are different mechanisms with different results.

**Routing heuristic:** ask "can this be a file?" before "can this be an OSC write?" A `.adg` built
offline needs no running Live, no consent gate, and no live-write risk — it is both cheaper and
safer than driving the set.

## Premake entry points (real signatures)

**Slice B — composition** (`sidekick/librarian/tutorial_match.py`):

- `match_progression(query: ProgressionQuery, index: Sequence[ChordRow]) -> ProgressionMatchResult` — ranks the indexed library; honest floor (score>0 only), deterministic tie-break by path, `NoQueryDimensionsError` on an empty query, `closest_weak` when nothing clears the floor (never a fabricated hit).
- `ProgressionQuery{key_root, key_mode, kind, progression}` — a `None` dimension means "unknown", never "any".
- `routes_to_progression_matcher(content_class, *, params=None)` — the routing seam; `content_class == "composition/MIDI"` and no FIDELITY marker.
- Stage the matched `ChordRow` UNCHANGED via `stage_chords` (`sidekick/librarian/stage.py`); `ChordRow.path` (an already-indexed `.mid`) is what gets parsed — never a synthesized substitute.

**Slice C — sound-design** (`sidekick/librarian/build_patch.py`, `sidekick/client.py`):

- `PatchStep{device, parameter, value, reachability: "stock"|"hybrid"|"manual"}` (ordered). Semantics: `hybrid` = load a device (no parameter); `stock` = set a param (device + parameter + value required); `manual` = a hard wall, refused + reported.
- `validate_recipe(...)` rejects malformed recipes BEFORE any write: empty, hybrid-carrying-a-parameter, stock-missing-param/value, and the ordering invariant (a param-set's device must be loaded by an earlier step). Structural validation runs on DECLARED reachability, before the FIDELITY→MANUAL downgrade.
- `build_patch(...) -> BuildReport` — zero-reachable/only-manual → zero writes; HYBRID loads + STOCK param-sets in order; MANUAL steps refused + reported, driver CONTINUES; mid-sequence failure → `PartialBuildError` naming what landed/failed/never-attempted (loud, never silent-partial).
- `SidekickClient.get_device_parameter` / `set_device_parameter` — resolve param by name; `set` is master-chain-guarded before any transport call; write→read-back verify with `_param_value_equal_with_tolerance` (relative, not flat — a normalized-`[0,1]` param must not be verified with a Hz-magnitude tolerance).

## Source fetch reachability (the render wall)

The guru's WebFetch reads plain-article HTML. Two page classes it can't, and how far each tier reaches
(spike-verified 2026-09-26):

| Page class | WebFetch | headless render (`queue render-drain`) | real-browser (claude-in-chrome) |
| --- | --- | --- | --- |
| plain article | ✅ | — | — |
| JS-rendered | ❌ shell only | ✅ (adsr: 200 + 11.8k chars) | ✅ |
| Cloudflare/anti-bot | ❌ 403 | ❌ 403 "Just a moment" (reverb/macprovideo) | ✅ (real cookies) |

Headless render crosses the **JS-rendering** wall but **NOT Cloudflare's active challenge** — that is a
render wall crossed only by the real-browser (claude-in-chrome) fallback, tracked by the
`needs_browser` queue status. Do not add a stealth arms-race; the wall is real and dated.

## Source

Distilled from `crew/design-tutorial-to-ableton.md` §2 (worked classifier), `crew/researcher.md` §7–§8
(library-match narrowing + live grounding), and the GATE-2 live drive on 2026-07-16 (URI scheme +
normalized-range calibration finding). The permanent ADR is `docs/decisions/tutorials1.md`.

**Superseded:** `crew/spike-rack-automation.md` §1.5 (the "12.2.5 walls") is a historical record of
what was believed in July 2026 — it is NOT a current contract. Its rack/macro/zone/automation walls
are all refuted above. Left as written; do not route from it.

**Lesson.** A reachability table is a _contract that decays_. It was wrong in the expensive
direction — declaring things impossible — so no one retried them, and the error was self-sealing.
Re-verify a MANUAL row against shipped code before accepting it, and date any wall you add.

**How to re-verify a LOM wall — use the LIVE probe, not bytecode.**

> ⚠️ **A bytecode check of `LomTypes.pyc` gave a FALSE NEGATIVE on 2026-07-22.** It reported
> `insert_chain` absent from 12.3.2; the live probe then found it **present**. `_MxDCore/LomTypes.pyc`
> is the **Max-for-Live** type whitelist — AbletonOSC is a **Remote Script** using the Python LOM
> directly and is not bound by it. Absence there proves nothing about the bridge. This nearly
> hardened a wall that does not exist.

**The authoritative test** (read-only, one call, no writes):

```python
from sidekick.connect import connect
with connect(crew="probe") as c:
    print(c._t.query("/live/device/probe_construction", (track, device, 0), timeout=8.0))
    # -> ('device:insert_chain', 'chain:insert_device')  on 12.3.2
```

It `hasattr`-probes the real objects in the running Live, so it answers for the build you actually
have. Run it before writing or trusting ANY construction wall row.

<details><summary>The bytecode method (kept only as a caveat — do not rely on it)</summary>

```sh
L="/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/MIDI Remote Scripts/_MxDCore/LomTypes.pyc"
strings "$L" | grep -x insert_device        # PRESENT on 12.3.2
strings "$L" | grep -x insert_chain         # absent  on 12.3.2
```

The property lists are stored per-class and alphabetised, so a window of surrounding strings
identifies the owning class. It is fast, but it answers *"is this exposed to M4L?"* — **not**
*"can the bridge call it?"* Those differ, as `insert_chain` proved.

</details>
