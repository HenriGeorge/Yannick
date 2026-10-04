// tokens.mjs — CSS custom-property hex → Figma COLOR variables (generalized from the source
// tokens-to-figma harness). Everything project-specific is now a flag:
//   --css=<file>          the stylesheet to read custom properties from   (formerly a hardcoded path)
//   --prefix=<str>        custom-property prefix to match, e.g. --x-       (was hardcoded --dk-)
//   --collection=<name>   the Figma variable collection to write into      (was hardcoded "terminal")
//   --channel=<id>        talk-to-figma channel (repeatable); auto-resolved otherwise (FIGMA_CHANNEL)
//   --file-key=<key>      disambiguate live channels by file fingerprint
//   --dry-run             parse + report only; write nothing, touch no relay (offline)
//
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { readFileSync } from "node:fs";
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";

// --k=v → flags.k ; repeated --channel=… → channels[] ; bare --k → flags.k=true.
function parseFlags(args) {
  const flags = {};
  const channels = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) {
      if (m[1] === "channel") channels.push(m[2]);
      else flags[m[1]] = m[2];
    } else if (a.startsWith("--")) flags[a.slice(2)] = true;
  }
  return { flags, channels };
}

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
function hexToRgba(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255, a: 1 };
}
function parseTokens(css, prefix) {
  const out = [];
  // Accept a 6-hex color followed by any valid trailing CSS (`!important`, whitespace) up to the `;`.
  // The `(?![0-9a-fA-F])` lookahead rejects an 8-digit `#rrggbbaa` (would else silently truncate to 6);
  // that genuine drop is still caught by the declared-vs-parsed guard below.
  const re = new RegExp(`${esc(prefix)}([a-zA-Z0-9-]+)\\s*:\\s*(#[0-9a-fA-F]{6})(?![0-9a-fA-F])[^;]*;`, "g");
  let m;
  while ((m = re.exec(css))) out.push({ name: m[1], hex: m[2].toLowerCase(), value: hexToRgba(m[2]) });
  return out;
}

const asObj = (r) => (typeof r === "string" ? JSON.parse(r) : r);
const near = (a, b) => Math.abs(a - b) < 0.01;

export async function run(args) {
  const { flags, channels } = parseFlags(args);
  if (!flags.css) throw new Error("tokens: --css=<file> is required");
  const prefix = flags.prefix ?? "--";
  const collection = flags.collection ?? "tokens";

  // Strip block comments ONCE, then parse + fail-loud guard against the same source (no asymmetry).
  const css = readFileSync(flags.css, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const tokens = parseTokens(css, prefix);
  if (!tokens.length) throw new Error(`tokens: no "${prefix}*" 6-digit-hex custom properties found in ${flags.css}`);
  // Every COLOR-VALUED declaration must parse: denominator is only `#…` attempts, so a malformed color
  // (3/8-digit hex) fails loud instead of being silently dropped.
  const declared = (css.match(new RegExp(`${esc(prefix)}[a-zA-Z0-9-]+\\s*:\\s*#[0-9a-fA-F]+`, "g")) || []).length;
  if (declared !== tokens.length) {
    throw new Error(
      `tokens: color-parse mismatch in ${flags.css} — ${declared} "${prefix}*: #…" declaration(s), ${tokens.length} parsed. ` +
        `Only 6-digit "#rrggbb" is supported. Parsed: ${tokens.map((t) => t.name).join(", ") || "(none)"}`,
    );
  }
  console.log(`parsed ${tokens.length} colors (prefix ${prefix}) → collection "${collection}": ${tokens.map((t) => t.name).join(", ")}`);
  if (flags["dry-run"]) {
    console.log(`dry-run: would sync ${tokens.length} variable(s) into "${collection}" (no relay touched)`);
    return;
  }

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  join(conn, channel);

  let vars = asObj(await rpc(conn, "get_variables", {}, 12000));
  let collectionId = vars.collections?.find((c) => c.name === collection)?.id;

  for (const t of tokens) {
    const where = collectionId ? { collectionId } : { collectionName: collection };
    await rpc(conn, "set_variable", { ...where, name: t.name, resolvedType: "COLOR", value: t.value });
    if (!collectionId) {
      vars = asObj(await rpc(conn, "get_variables", {}));
      collectionId = vars.collections.find((c) => c.name === collection)?.id;
    }
  }
  console.log(`wrote ${tokens.length} variables into "${collection}" (${collectionId})`);

  // read-back + assert
  const after = asObj(await rpc(conn, "get_variables", {}));
  const tcoll = after.collections.find((c) => c.name === collection);
  if (!tcoll) {
    close(conn);
    throw new Error(`tokens: read-back — "${collection}" collection not found`);
  }
  const modeId = tcoll.modes[0].modeId;
  let ok = 0;
  const fails = [];
  for (const t of tokens) {
    const got = tcoll.variables.find((x) => x.name === t.name)?.valuesByMode?.[modeId];
    if (got && near(got.r, t.value.r) && near(got.g, t.value.g) && near(got.b, t.value.b)) ok++;
    else fails.push(`${t.name} (${t.hex}) → ${got ? JSON.stringify(got) : "MISSING"}`);
  }
  close(conn);
  console.log(`read-back: ${ok}/${tokens.length} match`);
  if (fails.length) throw new Error("tokens: read-back mismatch:\n  " + fails.join("\n  "));
  console.log(`tokens OK — ${ok} variables synced + verified in "${collection}" (channel ${channel})`);
}
