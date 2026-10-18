// lanes.mjs — `figma.mjs lanes`: fan the single-channel plugin-run out over N Figma files.
// Zero-dep (Node core + the figma-bridge backbone). macOS-only for the UI/tmux half.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  ensureRelay, figmaReady, openFileWindow, runPluginForChannel, forcedProbeResult, portListening,
} from "./ctf-autolaunch.mjs";
import { probeChannel } from "./channel-resolve.mjs";

const LANE_RE = /^([A-Za-z0-9][\w-]*)=([A-Za-z0-9]+)(?:@(.+))?$/;

export function parseLanes(confValue, argv) {
  const errors = [];
  let max = process.env.FIGMA_LANES_MAX ? parseInt(process.env.FIGMA_LANES_MAX, 10) : 4, spawn = true, prime = null;
  const cliLanes = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--no-spawn") { spawn = false; continue; }
    if (a === "--max") { max = parseInt(argv[++i], 10); continue; }
    if (a.startsWith("--max=")) { max = parseInt(a.slice("--max=".length), 10); continue; }
    if (a === "--prime") { prime = argv[++i] ?? null; continue; }
    if (a.startsWith("--prime=")) { prime = a.slice("--prime=".length); continue; }
    if (a.includes("=")) cliLanes.push(a);
  }
  const raw = (cliLanes.length ? cliLanes : (confValue || "").trim().split(/\s+/)).filter(Boolean);
  const lanes = [];
  for (const tok of raw) {
    const m = LANE_RE.exec(tok);
    if (!m) { errors.push(`malformed lane: ${tok}`); continue; }
    const lane = { channel: m[1], fileKey: m[2] };
    if (m[3]) lane.cwd = m[3];
    lanes.push(lane);
  }
  if (!Number.isFinite(max) || max <= 0) max = 4;
  if (lanes.length === 0) errors.push("no lanes configured");
  if (lanes.length > 8) errors.push(`too many lanes (${lanes.length}); hard cap is 8`);
  return { lanes, max, spawn, prime, errors };
}

const PRIME_DEFAULT = (ch) =>
  `You are the Figma agent for channel '${ch}'. Call join_channel ${ch}, then await instructions.`;

// shq(s) — single-quote a string for safe interpolation into the `sh -c`-style tmux command
// argument. Never pass cwd/prime through JSON.stringify for this — that's JS-string-safe, not
// shell-safe (backticks/$(...)/$VAR still expand inside a double-quoted bash string).
const shq = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'";

// isLive(channel, socketUrl) — a PURE liveness probe (no keystrokes): honors the same
// CT_FIGMA_LANES_PROBE test knob as runPluginForChannel, otherwise calls probeChannel directly.
// probeChannel resolves {status, ...}; "live" iff status === "CONNECTED" (any other status, e.g.
// NOT_CONNECTED, is not-live). It itself never throws (it catches its own connect failure), but we
// guard anyway and breadcrumb any unexpected rejection instead of silently treating it as "not live".
async function isLive(channel, socketUrl) {
  const forced = forcedProbeResult(channel);
  if (forced !== null) return forced;
  try {
    const p = await probeChannel(channel, socketUrl);
    return p?.status === "CONNECTED";
  } catch (e) {
    process.stderr.write(`figma-lanes: probe error on '${channel}': ${e?.message ?? e}\n`);
    return false;
  }
}

// waitForRelay(fast) — poll the bridge port after ensureRelay() reports "spawned" so the FIRST
// lane doesn't race the relay's own startup. Best-effort: times out silently and lets the per-lane
// loop surface its own (accurate) failure reason if the relay still isn't up.
async function waitForRelay(fast) {
  const deadline = Date.now() + (fast ? 300 : 5000);
  if (await portListening(3055)) return true;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, fast ? 20 : 200));
    if (await portListening(3055)) return true;
  }
  return false;
}

// run(args) — sequential, probe-gated per-lane loop: for each configured lane, a PURE probe
// (isLive) decides idempotent skip-live vs needing the keystroke launch; only the latter opens the
// lane's Figma file and drives runPluginForChannel. Spawns one detached tmux session per green lane
// (unless --no-spawn), verifying the spawn itself before counting the lane live. Exits 1 if any
// lane failed to join OR failed to spawn.
export async function run(args) {
  const fast = process.env.CT_FIGMA_AUTOLAUNCH_FAST === "1";
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const { lanes, max, spawn, prime, errors } = parseLanes(process.env.FIGMA_LANES ?? "", args);
  if (errors.length) { errors.forEach((e) => process.stderr.write(`figma-lanes: ${e}\n`)); process.exit(1); }
  if (lanes.length > max) process.stdout.write(`figma-lanes: ${lanes.length} lanes exceed soft cap ${max} — continuing\n`);

  if (process.platform !== "darwin") { process.stdout.write("figma-lanes: macOS-only — no-op here\n"); return; }
  // Honor the SAME gates as the hook's autolaunch (reused, not re-decided): opt-out + import sentinel.
  if (process.env.FIGMA_AUTOLAUNCH_PLUGIN === "0") { process.stdout.write("figma-lanes: FIGMA_AUTOLAUNCH_PLUGIN=0 — skipped\n"); return; }
  const sentinel = path.join(os.homedir(), ".local", "share", "claude-template", "ctf-imported");
  if (!fs.existsSync(sentinel)) { process.stdout.write(`figma-lanes: import the CTF panel once, then: touch ${sentinel}\n`); return; }

  const relay = await ensureRelay();
  if (relay === "no-npx") {
    process.stderr.write("figma-lanes: relay unavailable (npx not found) — install Node/npx or start the bridge manually\n");
    process.exit(1);
  }
  if (relay === "spawned") await waitForRelay(fast);

  let green = [];
  const failed = [];
  for (const lane of lanes) {
    try {
      const already = await isLive(lane.channel, socketUrl);
      if (already) { green.push(lane); continue; }
      const openResult = openFileWindow(lane.fileKey);
      if (openResult?.error) process.stderr.write(`figma-lanes: open failed for lane '${lane.channel}': ${openResult.error.code ?? openResult.error.message}\n`);
      else if (openResult?.status) process.stderr.write(`figma-lanes: open rejected the URL for lane '${lane.channel}': exit ${openResult.status}\n`);
      const ready = await figmaReady(fast);
      if (ready !== "ready") {
        const reason = ready === "tcc"
          ? "accessibility/Screen-permission denied for Figma"
          : `figma not frontmost (${ready})`;
        failed.push({ ...lane, reason });
        continue;
      }
      const ok = await runPluginForChannel({ channel: lane.channel, socketUrl, fast });
      if (ok) green.push(lane);
      else failed.push({ ...lane, reason: `channel '${lane.channel}' never joined — the Figma file must be named exactly '${lane.channel}' and the plugin run in that window` });
    } catch (e) {
      failed.push({ ...lane, reason: `unexpected error: ${e?.message ?? e}` });
    }
  }

  if (spawn) {
    const spawnedOk = [];
    for (const lane of green) {
      const cwd = lane.cwd ?? process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
      const promptText = prime ?? PRIME_DEFAULT(lane.channel);
      const r = spawnSync("tmux", ["new-session", "-d", "-s", `figma-${lane.channel}`,
        `cd ${shq(cwd)} && claude ${shq(promptText)}`], { stdio: "ignore" });
      if (r.error || r.status !== 0) {
        const code = r.error ? (r.error.code ?? r.error.message) : r.status;
        process.stderr.write(`figma-lanes: tmux new-session failed for figma-${lane.channel}: ${code}\n`);
        failed.push({ ...lane, reason: `tmux new-session failed: ${code}` });
      } else {
        spawnedOk.push(lane);
      }
    }
    green = spawnedOk;
  }

  process.stdout.write(`figma-lanes: ${green.length} live (${green.map((l) => l.channel).join(", ") || "none"})\n`);
  for (const f of failed) process.stderr.write(`figma-lanes: lane '${f.channel}' FAILED — ${f.reason}\n`);
  if (spawn && green.length) process.stdout.write("attach: tmux attach  (one window per lane)\n");
  process.exit(failed.length ? 1 : 0);
}
