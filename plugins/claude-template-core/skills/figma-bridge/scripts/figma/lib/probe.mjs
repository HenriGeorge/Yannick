// probe.mjs — READ-ONLY channel probe: for each candidate channel report the current page, page count,
// page names/ids, and a `fileKey` file fingerprint. Thin CLI over channel-resolve's probeChannel (no
// inline socket/probe loop — the backbone owns that).
//   --channel=<id>   candidate channel (repeatable); FIGMA_CHANNEL also seeds one.
// Zero-dep: Node core + the shared channel-resolve backbone only.
import { probeChannel, folderChannel, discoverChannels } from "./channel-resolve.mjs";

// httpFromWs(wsUrl) — the relay's HTTP status endpoint shares the ws port; ws→http, wss→https.
export function httpFromWs(wsUrl) {
  return wsUrl.replace(/^ws(s?):\/\//, (_, s) => `http${s}://`);
}

// baseFromChannels(names) — strip a trailing _<n> off each channel and return the single most-common
// stem (the project's Figma file name). Throws on an empty list or a tie between distinct stems,
// because one project is one file is one base (spec: base discovery).
export function baseFromChannels(names) {
  if (!names.length) throw new Error("no channels to derive a base from");
  const counts = new Map();
  for (const n of names) {
    const stem = n.replace(/_\d+$/, "");
    counts.set(stem, (counts.get(stem) ?? 0) + 1);
  }
  const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  if (ranked.length > 1 && ranked[0][1] === ranked[1][1]) {
    throw new Error(`ambiguous base among channels: ${[...counts.keys()].join(", ")}`);
  }
  return ranked[0][0];
}

// evaluateAll(results) — pass iff every channel is CONNECTED and all non-null fileKeys agree.
export function evaluateAll(results) {
  const missing = results.filter((r) => r.status !== "CONNECTED").map((r) => r.channel);
  const keys = results.filter((r) => r.fileKey != null).map((r) => r.fileKey);
  const majority = keys.length ? keys.sort(
    (a, b) => keys.filter((k) => k === b).length - keys.filter((k) => k === a).length,
  )[0] : null;
  const split = results.filter((r) => r.fileKey != null && r.fileKey !== majority);
  const reasons = [];
  if (missing.length) reasons.push(`${results.length - missing.length}/${results.length} live (missing ${missing.join(", ")})`);
  if (split.length) reasons.push(`fileKey split: ${split.map((r) => `${r.channel} on ${r.fileKey}`).join(", ")}, rest ${majority}`);
  return { pass: reasons.length === 0, reason: reasons.join("; ") };
}

// statusChannels(httpUrl) — the relay's /status lists every live channel; a dead or odd endpoint
// returns [] so the caller can fall back, never throws.
export async function statusChannels(httpUrl) {
  try {
    const res = await fetch(`${httpUrl}/status`, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) return [];
    const json = await res.json();
    return (json?.queue?.channels ?? []).map((c) => c.channel).filter(Boolean);
  } catch {
    return []; // relay down / non-JSON / timeout → caller falls back to folderChannel()
  }
}

// resolveBase — explicit --base wins; else the live channel stem; folderChannel() is the last resort
// because a renamed Figma file makes the folder name wrong (hence the warn).
export async function resolveBase(args, httpUrl) {
  const flag = args.find((a) => a.startsWith("--base="));
  if (flag) return flag.split("=")[1];
  const live = await statusChannels(httpUrl);
  if (live.length) return baseFromChannels(live);
  console.error("warn: no channels in /status; falling back to folderChannel() (often wrong for a renamed file)");
  return folderChannel();
}

export async function run(args) {
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  if (args.includes("--all")) {
    if (args.some((a) => a.startsWith("--channel="))) {
      console.error("probe --all and --channel are mutually exclusive");
      process.exit(2);
    }
    const maxArg = args.find((a) => a.startsWith("--max="));
    const max = maxArg ? parseInt(maxArg.split("=")[1], 10) : 5;
    if (!Number.isInteger(max) || max < 1) {
      console.error("probe --all: --max must be a positive integer");
      process.exit(2);
    }
    const httpUrl = httpFromWs(socketUrl);
    const base = await resolveBase(args, httpUrl);
    const channels = Array.from({ length: max }, (_, i) => `${base}_${i + 1}`);
    const results = await Promise.all(channels.map((c) => probeChannel(c, socketUrl)));
    console.log(JSON.stringify(results, null, 2));
    for (const r of results) {
      console.error(`${r.channel.padEnd(24)} ${r.status.padEnd(14)} pages=${r.pageCount ?? "-"} fileKey=${r.fileKey ?? "-"}`);
    }
    const { pass, reason } = evaluateAll(results);
    console.error(pass ? `OK: ${results.length}/${results.length} reachable, one file` : `FAIL: ${reason}`);
    process.exit(pass ? 0 : 1);
  }
  const channels = args.filter((a) => a.startsWith("--channel=")).map((a) => a.split("=")[1]);
  if (process.env.FIGMA_CHANNEL) channels.push(process.env.FIGMA_CHANNEL);
  if (!channels.length) {
    // No explicit channel: discover the live channel(s) from the relay /status endpoint; a dead relay
    // yields [] → keep the bare folder-name default (FT16/FT18 fail-open contract).
    const discovered = await discoverChannels(socketUrl);
    if (discovered.length) channels.push(...discovered);
    else channels.push(folderChannel());
  }
  const results = await Promise.all(channels.map((c) => probeChannel(c, socketUrl)));
  console.log(JSON.stringify(results, null, 2));
}
