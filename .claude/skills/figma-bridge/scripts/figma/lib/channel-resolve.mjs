// channel-resolve.mjs — the ONE channel probe + fileKey-match + live-channel selection (triplicated
// across the source scripts). Built on relay-client; every subcommand resolves its target channel here
// instead of re-implementing a probe loop.
//
// fileKey = sha1(sorted page ids).slice(0,8): a stable file fingerprint. The plugin exposes no
// figma.root name/id, so page name is NOT a file identifier — page ids are. Caveat: a brand-new
// single-page file is always {0:1}, so empty files collide; any real file has distinct page ids.
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { basename, dirname } from "node:path";
import { connect, join, rpc, close } from "./relay-client.mjs";

// folderChannel() — the deterministic default channel = basename of the MAIN working tree, so it is
// identical across every worktree of the project ("one project = one Figma file = one channel"). Derives
// from `git rev-parse --git-common-dir` (→ the main checkout's .git), realpath'd, up one dir, basenamed —
// which is stable from any worktree, unlike basename(cwd). Total: falls back to the cwd basename outside
// a git repo (rare). Never throws.
export function folderChannel() {
  try {
    const gitCommonDir = execFileSync("git", ["rev-parse", "--git-common-dir"], {
      encoding: "utf8",
    }).trim();
    // ponytail: current git re-anchors `--git-common-dir` to the cwd (`../.git` from a subdir), so
    // realpath+dirname resolves to the repo root from anywhere. But an OLDER git returning a bare
    // relative `.git`, or a detached/edge layout, would realpath against the SUBDIR instead → ENOENT →
    // the catch falls back to the subdir basename (wrong channel). Safe for cwd = repo root (all toolkit
    // + test invocations); switch to `--show-toplevel` if a real subdir-cwd invocation surfaces (#830).
    return basename(dirname(realpathSync(gitCommonDir)));
  } catch {
    return basename(realpathSync(process.cwd()));
  }
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
  if (channels.length === 0) return folderChannel();
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
