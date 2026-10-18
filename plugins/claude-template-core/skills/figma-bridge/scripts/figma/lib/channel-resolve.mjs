// channel-resolve.mjs — the ONE channel probe + fileKey-match + live-channel selection (triplicated
// across the source scripts). Built on relay-client; every subcommand resolves its target channel here
// instead of re-implementing a probe loop.
//
// fileKey = sha1(sorted page ids).slice(0,8): a stable file fingerprint. The plugin exposes no
// figma.root name/id, so page name is NOT a file identifier — page ids are. Caveat: a brand-new
// single-page file is always {0:1}, so empty files collide; any real file has distinct page ids.
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { realpathSync, readFileSync } from "node:fs";
import { basename, dirname } from "node:path";
import { connect, join, rpc, close } from "./relay-client.mjs";

// folderChannel() — the deterministic default channel = basename of the MAIN working tree, so it is
// identical across every worktree of the project ("one project = one Figma file = one DEFAULT channel";
// the multi-channel panel can add further channels in the same window, this is just the auto-join one). Derives
// from `git rev-parse --git-common-dir` (→ the main checkout's .git), realpath'd, up one dir, basenamed —
// which is stable from any worktree, unlike basename(cwd). Total: falls back to the cwd basename outside
// a git repo (rare). Never throws.
// figmaFileKey(env) — the immutable Figma file key for this project, if known: env `FIGMA_FILE_KEY`
// first (so a caller/test can inject), then `FIGMA_FILE_KEY="..."` in the main checkout's
// `.claude/worktrees.conf`. Empty string when unknown. Never throws (fail-open, like folderChannel).
export function figmaFileKey(env = process.env) {
  let key = "";
  if (env.FIGMA_FILE_KEY) {
    key = String(env.FIGMA_FILE_KEY).trim();
  } else {
    try {
      const gitCommonDir = execFileSync("git", ["rev-parse", "--git-common-dir"], { encoding: "utf8" }).trim();
      const root = dirname(realpathSync(gitCommonDir));
      const conf = readFileSync(`${root}/.claude/worktrees.conf`, "utf8");
      const m = conf.match(/^\s*FIGMA_FILE_KEY=["']?([^"'\n]+)/m);
      key = m ? m[1].trim() : "";
    } catch {
      return "";
    }
  }
  // Validate like the figma_launch hooks do (`[A-Za-z0-9]+`): a real Figma file key is alphanumeric.
  // A malformed key degrades to "" → bare folder, so the CLI's offline default matches the hooks'
  // (no `<badkey>_folder` divergence) — the label never carries unexpected chars.
  return /^[A-Za-z0-9]+$/.test(key) ? key : "";
}

export function folderChannel(env = process.env) {
  let folder;
  try {
    const gitCommonDir = execFileSync("git", ["rev-parse", "--git-common-dir"], {
      encoding: "utf8",
    }).trim();
    // ponytail: current git re-anchors `--git-common-dir` to the cwd (`../.git` from a subdir), so
    // realpath+dirname resolves to the repo root from anywhere. But an OLDER git returning a bare
    // relative `.git`, or a detached/edge layout, would realpath against the SUBDIR instead → ENOENT →
    // the catch falls back to the subdir basename (wrong channel). Safe for cwd = repo root (all toolkit
    // + test invocations); switch to `--show-toplevel` if a real subdir-cwd invocation surfaces (#830).
    folder = basename(dirname(realpathSync(gitCommonDir)));
  } catch {
    folder = basename(realpathSync(process.cwd()));
  }
  // Prefix the immutable file key when known, so the offline default matches the panel's
  // "<fileKey>_<fileName>" base (the live /status discovery path is name-agnostic and unaffected).
  const key = figmaFileKey(env);
  return key ? `${key}_${folder}` : folder;
}

// discoverChannels(socketUrl) -> Promise<string[]> — ground-truth channel discovery from the relay's
// HTTP /status endpoint. Reads queue.channels[].channel and expands each `Base_<n>` to the panel's
// default family Base_1..5 (queue.channels under-reports — it lists only queue-active channels, not all
// 5 joined rows). Fails OPEN: any unreachable/non-200/bad-JSON/timeout → []. Callers fall back to
// folderChannel(), so a dead relay never regresses an explicit-channel or offline call.
export async function discoverChannels(socketUrl, { timeoutMs = 1500 } = {}) {
  const origin = (socketUrl ?? "ws://localhost:3055").replace(/^ws/, "http").replace(/\/+$/, "");
  let body;
  try {
    const res = await fetch(`${origin}/status`, { signal: AbortSignal.timeout(timeoutMs) });
    if (!res.ok) return [];
    body = await res.json();
  } catch {
    return [];
  }
  const raw = (body?.queue?.channels ?? [])
    .map((c) => c?.channel)
    .filter((s) => typeof s === "string" && s.length > 0);
  const out = [];
  const seen = new Set();
  const add = (name) => { if (!seen.has(name)) { seen.add(name); out.push(name); } };
  for (const ch of raw) {
    const m = ch.match(/^(.*)_(\d+)$/);
    if (m) for (let i = 1; i <= 5; i++) add(`${m[1]}_${i}`);
    else add(ch);
  }
  return out;
}

// probeChannel(channel, socketUrl) -> {channel, status, currentPage?, pageCount?, pageNames?, pageIds?, fileKey?}
export async function probeChannel(channel, socketUrl) {
  let conn;
  try {
    conn = await connect(socketUrl);
  } catch {
    return { channel, status: "NOT_CONNECTED" };
  }
  join(conn, channel);
  await new Promise((r) => setTimeout(r, 250)); // let the plugin process the join before we ask
  let pages = null;
  try {
    pages = await rpc(conn, "get_pages", {}, 5000);
  } catch {
    /* watchdog / no plugin joined on this channel */
  }
  close(conn);
  if (!pages) return { channel, status: "NOT_CONNECTED" };
  const list = pages.pages || [];
  const curId = pages.currentPageId || pages.currentPage?.id;
  const cur = list.find((p) => p.id === curId) || list.find((p) => p.isCurrent) || list[0];
  const pageIds = list.map((p) => p.id);
  const fileKey = pageIds.length
    ? createHash("sha1").update([...pageIds].sort().join(",")).digest("hex").slice(0, 8)
    : null;
  return {
    channel,
    status: "CONNECTED",
    currentPage: cur?.name ?? null,
    pageCount: list.length,
    pageNames: list.map((p) => p.name),
    pageIds,
    fileKey,
  };
}

// resolveChannel({channels, fileKey, env}) -> channel. `FIGMA_CHANNEL` (or an explicit channel already
// in `channels` of length 1) short-circuits; otherwise probe every candidate and pick the single live
// one (optionally filtered to `fileKey`), or throw listing each candidate's fingerprint.
export async function resolveChannel({ channels = [], fileKey, env = process.env }) {
  const socketUrl = env.FIGMA_WS_URL ?? "ws://localhost:3055";
  if (env.FIGMA_CHANNEL) return env.FIGMA_CHANNEL;
  if (channels.length === 1) return channels[0];
  if (channels.length === 0) {
    // Discover live channels from the relay /status before falling back to the folder name; a dead
    // relay yields [] → keep the folder-name default (FT16/FT18 fail-open contract).
    const discovered = await discoverChannels(socketUrl);
    if (!discovered.length) return folderChannel(env);
    channels = discovered; // fall through to the probe-and-pick-single-live logic below
  }
  const results = await Promise.all(channels.map((c) => probeChannel(c, socketUrl)));
  let live = results.filter((r) => r.status === "CONNECTED");
  if (fileKey) live = live.filter((r) => r.fileKey === fileKey);
  if (live.length === 1) return live[0].channel;
  if (live.length === 0) throw new Error(`no live channel among: ${channels.join(", ")}`);
  throw new Error(
    "multiple live channels — disambiguate with --channel:\n" +
      live.map((r) => `  ${r.channel} (fileKey ${r.fileKey})`).join("\n"),
  );
}
