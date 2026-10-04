// ctf-autolaunch.mjs — macOS UI driver for the ClaudeTalkToFigma plugin, shared by `figma.mjs lanes`.
// KEYSTROKE_SCRIPT is kept byte-identical to figma_launch.cjs (tests/test_figma_lanes.sh FL-LANES-07).
import net from "node:net";
import fs from "node:fs";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";
import { probeChannel } from "./channel-resolve.mjs";

export const KEYSTROKE_SCRIPT = [
  'tell application "System Events"',
  'key code 53', 'delay 0.3',
  'keystroke "p" using command down', 'delay 0.6',
  'keystroke "ClaudeTalkToFigma"', 'delay 0.6',
  'key code 36', 'end tell',
].join('\n');

const BRIDGE_PACKAGE = "claude-talk-to-figma-mcp@latest";
const BRIDGE_BIN = "claude-talk-to-figma-mcp-socket";
const BIND_WARNING = "WARNING: bridge binds 0.0.0.0:3055 (LAN-exposed, unauthenticated) — firewall :3055 or trusted network only.";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function osa(script, timeoutMs = 10000) {
  const r = spawnSync("osascript", ["-e", script], { encoding: "utf8", timeout: timeoutMs });
  if (!r || r.error) return null;
  return { status: r.status, stdout: r.stdout };
}

export async function figmaReady(fast) {
  const deadline = Date.now() + (fast ? 2000 : 20000);
  do {
    osa('tell application "Figma" to activate');
    const r = osa('tell application "System Events" to get name of first application process whose frontmost is true');
    if (!r) return "notfront";
    if (r.status !== 0) return "tcc";
    if ((r.stdout || "").trim() === "Figma") return "ready";
    await sleep(fast ? 50 : 500);
  } while (Date.now() < deadline);
  return "notfront";
}

export function portListening(port) {
  return new Promise((resolve) => {
    const sock = net.connect({ host: "127.0.0.1", port, timeout: 1000 });
    sock.on("connect", () => { sock.destroy(); resolve(true); });
    sock.on("timeout", () => { sock.destroy(); resolve(false); });
    sock.on("error", () => resolve(false));
  });
}

// onPath(bin) — mirrors figma_launch.cjs's helper: `command`/`which` are shell builtins/externals
// that behave inconsistently across shells, so resolve PATH ourselves (fs.accessSync per dir).
function onPath(bin) {
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    try { fs.accessSync(path.join(dir, bin), fs.constants.X_OK); return true; } catch { /* next dir */ }
  }
  return false;
}

export async function ensureRelay(port = 3055) {
  // Test-only short-circuit (same spirit as CT_FIGMA_LANES_PROBE): force ensureRelay's return
  // value without touching the port probe / npx lookup / real spawn. Unset in production.
  if (process.env.CT_FIGMA_LANES_RELAY) return process.env.CT_FIGMA_LANES_RELAY;
  const probePort = process.env.CT_FIGMA_PROBE_PORT ? Number(process.env.CT_FIGMA_PROBE_PORT) : port;
  if (await portListening(probePort)) return "up";
  if (!onPath("npx")) return "no-npx";
  process.stdout.write(BIND_WARNING + "\n");
  const child = spawn("npx", [`--package=${BRIDGE_PACKAGE}`, BRIDGE_BIN], { detached: true, stdio: "ignore" });
  child.on("error", (e) => { process.stdout.write(`bridge spawn failed: ${e.code || e.message}\n`); });
  child.unref();
  return "spawned";
}

// openFileWindow(fileKey) — returns the spawnSync result so callers can log a failed open instead
// of silently assuming the window opened.
export function openFileWindow(fileKey) {
  return spawnSync("open", [`https://www.figma.com/design/${fileKey}`], { timeout: 10000 });
}

// forcedProbeResult(channel) — test-only short-circuit for `figma.mjs lanes` orchestration tests.
// CT_FIGMA_LANES_PROBE=green|red forces EVERY channel; a "chan:color,chan:color" form forces per
// channel (unlisted channel defaults red). Unset in production — real probeChannel() runs, no-op.
// Exported so lanes.mjs's own pure liveness pre-check (no keystrokes) can honor the same knob.
export function forcedProbeResult(channel) {
  const v = process.env.CT_FIGMA_LANES_PROBE;
  if (!v) return null;
  if (v.includes(":")) {
    for (const pair of v.split(",")) {
      const [ch, color] = pair.split(":");
      if (ch === channel) return color === "green";
    }
    return false;
  }
  return v === "green";
}

export async function runPluginForChannel({ channel, socketUrl, fast }) {
  const forced = forcedProbeResult(channel);
  if (forced !== null) return forced;
  // probe() — a genuine probe REJECTION is breadcrumbed before being treated as "not connected",
  // instead of silently swallowed into the generic file-naming failure reason downstream.
  const probe = () => probeChannel(channel, socketUrl)
    .then((p) => p?.status === "CONNECTED")
    .catch((e) => {
      process.stderr.write(`figma-lanes: probe error on '${channel}': ${e?.message ?? e}\n`);
      return false;
    });
  const cap = 3;
  let connected = await probe();
  let attempts = 0;
  while (!connected && attempts < cap) {
    osa(KEYSTROKE_SCRIPT, 15000);
    attempts++;
    await sleep(fast ? 50 : 1500);
    connected = await probe();
  }
  return connected;
}
