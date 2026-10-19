// arrange.mjs — tidy a page's top-level frames into vertical bands grouped by name prefix.
// Reads each top-level child's bounds (one get_node_info depth:0 at a time — the bulk-read sever
// gotcha), groups by the name prefix before a delimiter, shelf-packs (or grids) each group into a
// band, stacks the bands, and move_nodes everything into place. Moves stream SERIALLY over one
// socket (each rpc awaited) — no parallel burst, so the plugin never drops mid-run.
//
//   --page=<name>        operate on this page (default: current page)
//   --delimiter=<str>    group key = name text before this substring (default "—"); no match → "misc"
//   --cols=<n>           force an N-column grid per band (default: shelf-pack by width budget)
//   --budget=<px>        shelf-pack row-width budget (default 7200)
//   --col-gap=<px>       gap between cells in a row (default 160)
//   --row-gap=<px>       gap between rows in a band (default 300)
//   --band-gap=<px>      gap between bands (default 700)
//   --start-x --start-y  layout origin (default 0, 0)
//   --group-sort=name|count|size   band order (default name)
//   --sort=name|none     order within a band (default name)
//   --no-glue            do NOT keep frames fully contained in another frame glued to it (default: glue ON)
//   --include=<substr>   only arrange frames whose name contains this (repeatable)
//   --exclude=<substr>   skip frames whose name contains this (repeatable)
//   --dry-run            compute + print the plan, move nothing
//   --channel=<id>       talk-to-figma channel (repeatable); auto-resolved otherwise
//   --file-key=<k>       disambiguate live channels by file fingerprint
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";
import { readFrames } from "./read-frames.mjs";

function parseFlags(args) {
  const flags = {};
  const channels = [], include = [], exclude = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) {
      if (m[1] === "channel") channels.push(m[2]);
      else if (m[1] === "include") include.push(m[2]);
      else if (m[1] === "exclude") exclude.push(m[2]);
      else flags[m[1]] = m[2];
    } else if (a.startsWith("--")) flags[a.slice(2)] = true;
  }
  return { flags, channels, include, exclude };
}

const num = (v, d) => (v === undefined ? d : Number(v));

// shelf-pack a list of cells [{...,w,h}] into rows within `budget`, from (startX,startY).
export function shelf(cells, startX, startY, budget, colGap, rowGap) {
  let x = startX, y = startY, rowH = 0;
  const out = [];
  for (const c of cells) {
    if (x > startX && (x - startX) + c.w > budget) { y += rowH + rowGap; x = startX; rowH = 0; }
    out.push({ ...c, nx: x, ny: y });
    x += c.w + colGap; rowH = Math.max(rowH, c.h);
  }
  return { placed: out, bottom: y + rowH };
}

// fixed-column grid: row height = tallest cell in that row.
export function grid(cells, cols, startX, startY, colGap, rowGap) {
  const out = [];
  let y = startY;
  for (let i = 0; i < cells.length; i += cols) {
    const row = cells.slice(i, i + cols);
    const rowH = Math.max(...row.map((c) => c.h));
    let x = startX;
    for (const c of row) { out.push({ ...c, nx: x, ny: y }); x += c.w + colGap; }
    y += rowH + rowGap;
  }
  return { placed: out, bottom: y - rowGap };
}

export const prefix = (name, delim) => {
  const i = name.indexOf(delim);
  return i > 0 ? name.slice(0, i).trim() : "misc";
};
// strict containment of A inside B (absolute bounds), B strictly larger.
export const contains = (B, A) =>
  B.ax <= A.ax && B.ay <= A.ay &&
  B.ax + B.w >= A.ax + A.w && B.ay + B.h >= A.ay + A.h &&
  B.w * B.h > A.w * A.h;

export async function run(args) {
  const { flags, channels, include, exclude } = parseFlags(args);
  const delim = flags.delimiter ?? "—";
  const budget = num(flags.budget, 7200);
  const colGap = num(flags["col-gap"], 160);
  const rowGap = num(flags["row-gap"], 300);
  const bandGap = num(flags["band-gap"], 700);
  const startX = num(flags["start-x"], 0);
  const startY = num(flags["start-y"], 0);
  const cols = flags.cols !== undefined ? Number(flags.cols) : null;
  const glue = !flags["no-glue"];
  const dryRun = !!flags["dry-run"];
  // Reject non-numeric numeric flags (e.g. --cols=abc → NaN → a degenerate/empty layout).
  for (const [name, val] of Object.entries({ budget, "col-gap": colGap, "row-gap": rowGap, "band-gap": bandGap, "start-x": startX, "start-y": startY })) {
    if (!Number.isFinite(val)) throw new Error(`arrange: --${name} must be a number`);
  }
  if (cols !== null && (!Number.isFinite(cols) || cols < 1)) throw new Error("arrange: --cols must be a positive integer");

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  join(conn, channel);
  try {
    // List top-level frames + bounds via the shared sever-safe reader (switches page if named).
    const frames = await readFrames(conn, { include, exclude, page: flags.page });
    if (!frames.length) throw new Error("arrange: no frames with bounds to arrange");

    // Glue: a frame fully inside another is an overlay — exclude from cells, move by its parent's delta.
    const glued = []; // {frame, parent}
    let cells = frames;
    if (glue) {
      cells = [];
      for (const f of frames) {
        let parent = null;
        for (const b of frames) {
          if (b === f || !contains(b, f)) continue;
          if (!parent || b.w * b.h < parent.w * parent.h) parent = b; // smallest container
        }
        if (parent) glued.push({ frame: f, parent }); else cells.push(f);
      }
    }

    // Group remaining cells by name prefix.
    const groups = new Map();
    for (const c of cells) {
      const key = prefix(c.name, delim);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(c);
    }
    if ((flags.sort ?? "name") !== "none") {
      for (const list of groups.values()) list.sort((a, b) => a.name.localeCompare(b.name));
    }
    let keys = [...groups.keys()];
    const gs = flags["group-sort"] ?? "name";
    if (gs === "count") keys.sort((a, b) => groups.get(b).length - groups.get(a).length);
    else if (gs === "size") keys.sort((a, b) => Math.max(...groups.get(b).map((c) => c.w * c.h)) - Math.max(...groups.get(a).map((c) => c.w * c.h)));
    else keys.sort((a, b) => a.localeCompare(b));

    // Lay out bands top-to-bottom.
    const plan = []; // {id,name,nx,ny}
    const newPos = new Map();
    let y = startY;
    for (const key of keys) {
      const list = groups.get(key);
      const band = cols ? grid(list, cols, startX, y, colGap, rowGap)
                        : shelf(list, startX, y, budget, colGap, rowGap);
      for (const p of band.placed) { plan.push({ id: p.id, name: p.name, nx: p.nx, ny: p.ny }); newPos.set(p.id, [p.nx, p.ny]); }
      y = band.bottom + bandGap;
    }
    // Glued overlays follow their nearest PLACED ancestor by the same delta. A glue chain (overlay →
    // glued container → placed frame) is rigid, so every link shifts by the top placed ancestor's
    // delta; walk up the glue map until a placed frame (handles nested overlays, not just one level).
    const gluedParent = new Map(glued.map((g) => [g.frame.id, g.parent]));
    for (const { frame } of glued) {
      let anc = gluedParent.get(frame.id);
      while (anc && !newPos.has(anc.id) && gluedParent.has(anc.id)) anc = gluedParent.get(anc.id);
      const np = anc && newPos.get(anc.id);
      if (!np) { process.stderr.write(`  skip overlay ${frame.name} (no placed ancestor)\n`); continue; }
      const dx = np[0] - anc.ox, dy = np[1] - anc.oy;
      plan.push({ id: frame.id, name: `${frame.name} (glued→${anc.name})`, nx: frame.ox + dx, ny: frame.oy + dy });
    }

    const bands = keys.map((k) => `${k}(${groups.get(k).length})`).join(" ");
    process.stderr.write(`[${channel}] bands: ${bands}${glued.length ? ` +${glued.length} glued` : ""}\n`);
    if (dryRun) {
      for (const p of plan) process.stdout.write(`  ${p.id.padEnd(14)} ${String(Math.round(p.nx)).padStart(6)} ${String(Math.round(p.ny)).padStart(7)}  ${p.name}\n`);
      console.log(`dry-run: ${plan.length} frames would move across ${keys.length} bands (no changes made)`);
      return;
    }
    let moved = 0;
    for (const p of plan) {
      await rpc(conn, "move_node", { nodeId: p.id, x: Math.round(p.nx), y: Math.round(p.ny) }, 30000);
      moved++;
      if (moved % 10 === 0) process.stderr.write(`  …${moved}/${plan.length}\n`);
    }
    console.log(`arranged ${moved} frames across ${keys.length} bands [${channel}]: ${bands}`);
  } finally {
    close(conn);
  }
}
