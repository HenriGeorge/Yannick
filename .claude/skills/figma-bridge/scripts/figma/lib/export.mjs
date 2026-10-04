// export.mjs — config-driven driver for the page→SVG→Figma pipeline (generalized from figma-export).
//   figma.mjs export [--config <path>] [--only "Name"] [--capture-only] [--no-capture]
//                    [--resolve-only] [--new-page "Name"] [--channel <id>]
// Phase 1: capture each config target → SVG (parallel chromium). Phase 2: validate (well-formed XML +
// <text>>0). Phase 3 (unless --capture-only): distribute set_svg round-robin across the resolved live
// channels, one writer per channel. Transitively captures, so it carries capture's lazy-dep guard: a
// missing playwright/esbuild/dom-to-svg surfaces the install hint, never a raw MODULE_NOT_FOUND stack.
//
// Config default outDir is `design/figma-src` (a neutral, project-agnostic default). See
// figma-export.config.example.json for the shape.
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { connect, join as joinChannel, rpc, close } from "./relay-client.mjs";
import { probeChannel, folderChannel } from "./channel-resolve.mjs";
import { capture, loadCaptureDeps } from "./capture.mjs";
import { ensureNamedPage } from "./page.mjs";

function parseArgs(args) {
  const flag = (name) => args.includes(`--${name}`);
  // accept both `--name value` and `--name=value`
  const val = (name) => {
    const eq = args.find((a) => a.startsWith(`--${name}=`));
    if (eq) return eq.slice(name.length + 3);
    const i = args.indexOf(`--${name}`);
    return i >= 0 ? args[i + 1] : null;
  };
  const channels = [];
  // accept both `--channel <id>` (space) and `--channel=<id>` (equals) — every sibling subcommand
  // takes the equals form, so export must too (code review, #541/O).
  args.forEach((a, i) => {
    if (a === "--channel" && args[i + 1]) channels.push(args[i + 1]);
    else if (a.startsWith("--channel=")) channels.push(a.slice("--channel=".length));
  });
  return {
    captureOnly: flag("capture-only"),
    noCapture: flag("no-capture"),
    resolveOnly: flag("resolve-only"),
    newPageName: val("new-page"),
    only: val("only"),
    cfgPath: val("config") ?? "figma-export.config.json",
    channels,
  };
}

const slug = (name) =>
  name
    .toLowerCase()
    .replace(/\(svg\)/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

async function pool(items, limit, fn) {
  const results = new Array(items.length);
  let i = 0;
  async function worker() {
    while (i < items.length) {
      const idx = i++;
      try {
        results[idx] = await fn(items[idx], idx);
      } catch (e) {
        results[idx] = { error: e.message };
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

function hasXmllint() {
  try {
    execFileSync("xmllint", ["--version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

function validate(path, xmllint) {
  if (!existsSync(path)) return { ok: false, reason: "missing file", textCount: 0, bytes: 0 };
  const svg = readFileSync(path, "utf8");
  const bytes = Buffer.byteLength(svg, "utf8");
  const textCount = (svg.match(/<text[\s>]/g) || []).length;
  let wellFormed = true;
  let reason = "";
  if (xmllint) {
    try {
      execFileSync("xmllint", ["--noout", path], { stdio: "pipe" });
    } catch {
      wellFormed = false;
      reason = "xmllint: not well-formed";
    }
  } else {
    const t = svg.trim();
    if (!/<svg[\s>]/i.test(t.slice(0, 300)) || !/<\/svg>\s*$/i.test(t)) {
      wellFormed = false;
      reason = "no <svg> root/close";
    }
    const badAmp = t.match(/&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/);
    if (badAmp) {
      wellFormed = false;
      reason = "unescaped &";
    }
  }
  const ok = wellFormed && textCount > 0;
  if (!ok && !reason) reason = textCount === 0 ? "<text>=0 (rasterized?)" : "unknown";
  return { ok, reason, textCount, bytes };
}

// Resolve the live channels for this run: probe the config channels (+ --channel + FIGMA_CHANNEL),
// keep the live ones (matched to cfg.fileKey when present). Round-robin distribution needs the full
// live set, so this probes directly rather than resolveChannel()'s single-channel pick.
async function resolveChannels({ cfg, cliChannels, socketUrl, env }) {
  const cand = new Set([...(cfg.channels || []), ...cliChannels]);
  if (env.FIGMA_CHANNEL) cand.add(env.FIGMA_CHANNEL);
  if (!cand.size) cand.add(folderChannel()); // default the candidate set to the repo folder name
  const probed = await Promise.all([...cand].map((c) => probeChannel(c, socketUrl)));
  let live = probed.filter((p) => p.status === "CONNECTED");
  if (cfg.fileKey) live = live.filter((p) => p.fileKey === cfg.fileKey);
  if (!live.length) {
    throw new Error(
      `export: no LIVE channel${cfg.fileKey ? ` for fileKey ${cfg.fileKey}` : ""} — open the ClaudeTalkToFigma plugin (Command+P). ` +
        `probed: ${probed.map((p) => `${p.channel}=${p.status === "CONNECTED" ? p.fileKey : "dead"}`).join(", ")}`,
    );
  }
  return live.map((p) => p.channel);
}

export async function run(args) {
  const opts = parseArgs(args);
  const cfg = JSON.parse(readFileSync(opts.cfgPath, "utf8"));
  const outDir = cfg.outDir || "design/figma-src";
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";

  let targets = (cfg.targets || []).map((t) => {
    const file = t.file || `${slug(t.name)}.svg`;
    // Path-traversal guard: the config is operator-owned, but a stray `../` in `file` would let a
    // set_svg source (or a captured artifact) land outside outDir. Reject traversal, absolute paths.
    if (file.includes("..") || file.startsWith("/") || file.startsWith("\\")) {
      throw new Error(`export: illegal target file "${file}" — no "..", no absolute path`);
    }
    return { ...t, file, path: join(outDir, file) };
  });
  if (opts.only) {
    const q = opts.only.toLowerCase();
    targets = targets.filter((t) => t.name.toLowerCase().includes(q));
  }
  if (targets.length === 0) throw new Error("export: no targets matched");

  // ---- Phase 1: capture ------------------------------------------------------------------------
  if (!opts.noCapture && !opts.resolveOnly) {
    const deps = await loadCaptureDeps(); // lazy dep gate → install hint if absent
    console.log(`\n== CAPTURE (${targets.length} targets, parallel) ==`);
    const results = await pool(targets, 4, async (t) => {
      if (t.skipCapture) {
        console.log(`  · reuse existing  ${t.path}  (${t.name})`);
        return;
      }
      console.log(`  → capture ${t.name}  ${t.selector ? `[${t.selector}]` : "(full page)"}`);
      return capture(
        {
          url: t.url,
          outSvg: t.path,
          selector: t.selector,
          viewportWidth: t.viewport?.width,
          stripImages: t.stripImages,
          stripSelectors: cfg.stripSelectors || [],
          maxHeight: t.maxHeight ?? null,
          inlineRemote: t.inlineRemote ?? cfg.inlineRemote ?? false, // opt-in server-side image inline (SSRF-guarded)
        },
        deps,
      );
    });
    // A failed capture must be FATAL: validate() re-reads the target path from disk, so a stale SVG
    // left by an earlier run would pass validation and get shipped — a silent wrong-content write with
    // exit 0. Refuse the whole run if any attempted (non-skip) capture errored.
    const capFails = results
      .map((r, idx) => ({ r, t: targets[idx] }))
      .filter((x) => x.r && x.r.error);
    if (capFails.length) {
      throw new Error(
        `export: ${capFails.length} capture(s) failed — refusing to ship possibly-stale SVGs: ` +
          capFails.map((x) => `${x.t.name} (${x.r.error})`).join("; "),
      );
    }
  } else {
    console.log(opts.resolveOnly ? "\n== RESOLVE-ONLY (dry run) ==" : "\n== CAPTURE skipped (--no-capture) ==");
  }

  // ---- Phase 2: validate -----------------------------------------------------------------------
  if (!opts.resolveOnly) {
    const xmllint = hasXmllint();
    console.log(`\n== VALIDATE (xmllint=${xmllint}) ==`);
    const rows = targets.map((t) => ({ t, v: validate(t.path, xmllint) }));
    for (const { t, v } of rows) {
      console.log(`  ${t.name.padEnd(24)} <text>=${String(v.textCount).padEnd(6)} ${v.ok ? "PASS" : `FAIL (${v.reason})`}`);
    }
    const fails = rows.filter((r) => !r.v.ok);
    console.log(`\n${rows.length - fails.length}/${rows.length} PASS`);
    if (opts.captureOnly) {
      if (fails.length) throw new Error(`export: --capture-only, ${fails.length} FAIL(s)`);
      console.log("\n--capture-only: skipping Figma writes.");
      return;
    }
    if (fails.length) throw new Error(`export: refusing to write — fix FAILs first: ${fails.map((f) => f.t.name).join(", ")}`);
  }

  // ---- Phase 3: distribute round-robin ---------------------------------------------------------
  const channels = await resolveChannels({ cfg, cliChannels: opts.channels, socketUrl, env: process.env });
  console.log(`resolved channel(s): ${channels.join(", ")}`);
  if (opts.resolveOnly) return;

  let rr = 0;
  for (const t of targets) t._channel = t.channel || channels[rr++ % channels.length];
  const used = [...new Set(targets.map((t) => t._channel))];
  const writeResults = [];

  await Promise.all(
    used.map(async (channel) => {
      const conn = await connect(socketUrl);
      joinChannel(conn, channel);
      try {
        let pageId = null;
        if (opts.newPageName) {
          const p = await ensureNamedPage(conn, opts.newPageName);
          pageId = p.pageId;
          console.log(`channel ${channel}: page "${opts.newPageName}" id=${pageId} (created=${p.created})`);
        }
        const pageCache = new Map();
        async function pageIdFor(t) {
          if (!t.page) return pageId; // may be null → set_svg lands on the current page
          if (pageCache.has(t.page)) return pageCache.get(t.page);
          const p = await ensureNamedPage(conn, t.page);
          pageCache.set(t.page, p.pageId);
          return p.pageId;
        }
        for (const t of targets.filter((x) => x._channel === channel)) {
          const svgString = readFileSync(t.path, "utf8");
          try {
            const parentId = await pageIdFor(t);
            const res = await rpc(conn, "set_svg", { svgString, x: t.x, y: t.y, name: t.name, parentId }, 60000);
            const nodeId = res?.id || res?.nodeId;
            if (!nodeId) throw new Error("set_svg resolved without a node id (empty/odd reply) — treating as a failed write");
            console.log(`  ✓ ${t.name} → ${channel} node=${nodeId}`);
            writeResults.push({ name: t.name, channel, nodeId });
          } catch (e) {
            console.error(`  ✗ ${t.name} → ${channel}: ${e.message}`);
            writeResults.push({ name: t.name, channel, error: e.message });
          }
        }
      } finally {
        close(conn);
      }
    }),
  );

  console.log("\n== WRITE RESULTS ==");
  for (const r of writeResults) console.log(`  ${r.name.padEnd(24)} ${r.channel.padEnd(12)} ${r.nodeId || "ERROR: " + r.error}`);
  if (writeResults.some((r) => r.error)) throw new Error(`export: ${writeResults.filter((r) => r.error).length} write(s) FAILED`);
}
