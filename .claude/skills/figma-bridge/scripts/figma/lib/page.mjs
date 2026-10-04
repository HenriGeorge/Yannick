// page.mjs — ensure a Figma page named <name> exists, rename it, set it current; print its id
// (generalized from figma-page). Idempotent: an existing same-name page is reused, not duplicated.
// Tries command-name variants (bridge builds differ) and treats a set-current timeout as fire-and-forget.
//   --name=<pageName>   page to ensure (or a bare positional name)
//   --channel=<id>      talk-to-figma channel (repeatable); auto-resolved otherwise (FIGMA_CHANNEL)
//   --file-key=<k>      disambiguate live channels by file fingerprint
// Zero-dep: Node core + the shared relay-client / channel-resolve backbone only.
import { connect, join, rpc, close } from "./relay-client.mjs";
import { resolveChannel } from "./channel-resolve.mjs";

function parseFlags(args) {
  const flags = {};
  const channels = [];
  const positional = [];
  for (const a of args) {
    const m = /^--([^=]+)=(.*)$/.exec(a);
    if (m) {
      if (m[1] === "channel") channels.push(m[2]);
      else flags[m[1]] = m[2];
    } else if (a.startsWith("--")) flags[a.slice(2)] = true;
    else positional.push(a);
  }
  return { flags, channels, positional };
}

const UNKNOWN = /unknown command|not.*support|no.*command|invalid command/i;

async function getPages(conn) {
  const r = await rpc(conn, "get_pages", {}, 15000);
  return {
    list: r?.pages || [],
    currentId: r?.currentPageId || r?.currentPage?.id || r?.pages?.find((p) => p.isCurrent)?.id || r?.pages?.[0]?.id,
  };
}

async function tryCreatePage(conn, name) {
  const before = (await getPages(conn)).list.map((p) => p.id);
  let res;
  for (const params of [{ name }, {}]) {
    try {
      res = await rpc(conn, "create_page", params, 15000);
      break;
    } catch (e) {
      if (UNKNOWN.test(e.message)) continue;
      throw e;
    }
  }
  if (res === undefined) throw new Error("create_page unsupported");
  let id = res?.id || res?.pageId || res?.page?.id;
  if (!id) {
    const after = await getPages(conn);
    id = after.list.map((p) => p.id).find((pid) => !before.includes(pid)) || after.currentId;
  }
  return id;
}

async function tryRename(conn, pageId, name) {
  const attempts = [
    ["set_page_name", { pageId, name }],
    ["rename_page", { pageId, name }],
    ["set_node_properties", { nodeId: pageId, properties: { name } }],
    ["set_node_name", { nodeId: pageId, name }],
  ];
  for (const [cmd, params] of attempts) {
    try {
      await rpc(conn, cmd, params, 15000);
      return cmd;
    } catch (e) {
      if (UNKNOWN.test(e.message)) continue;
      throw new Error(`${cmd} failed: ${e.message}`);
    }
  }
  return null;
}

async function trySetCurrent(conn, pageId) {
  // Best-effort: set_svg carries an explicit parentId, so nothing depends on the active page. Some
  // bridge builds run set_current_page but never ack → treat a timeout as fire-and-forget.
  for (const cmd of ["set_current_page", "set_active_page"]) {
    try {
      await rpc(conn, cmd, { pageId }, 4000);
      return cmd;
    } catch (e) {
      if (/timeout/i.test(e.message)) return `${cmd} (no-ack)`;
      if (UNKNOWN.test(e.message)) continue;
      return `${cmd} (err: ${e.message})`;
    }
  }
  return null;
}

export async function ensureNamedPage(conn, name) {
  const { list } = await getPages(conn);
  const existing = list.find((p) => p.name === name);
  if (existing) {
    const setCurrentCmd = await trySetCurrent(conn, existing.id);
    return { pageId: existing.id, created: false, renameCmd: null, setCurrentCmd };
  }
  const pageId = await tryCreatePage(conn, name);
  const renameCmd = await tryRename(conn, pageId, name);
  const setCurrentCmd = await trySetCurrent(conn, pageId);
  return { pageId, created: true, renameCmd, setCurrentCmd };
}

export async function run(args) {
  const { flags, channels, positional } = parseFlags(args);
  const pageName = flags.name ?? positional[0];
  if (!pageName) throw new Error("page: --name=<pageName> (or a positional name) is required");

  const channel = await resolveChannel({ channels, fileKey: flags["file-key"], env: process.env });
  const socketUrl = process.env.FIGMA_WS_URL ?? "ws://localhost:3055";
  const conn = await connect(socketUrl);
  join(conn, channel);
  try {
    const r = await ensureNamedPage(conn, pageName);
    console.log(JSON.stringify({ channel, pageName, ...r }, null, 2));
    if (!r.pageId) throw new Error("page: PAGE_FAIL — no page id resolved");
    console.log(`PAGE_OK pageId=${r.pageId} created=${r.created} rename=${r.renameCmd} setCurrent=${r.setCurrentCmd}`);
  } finally {
    close(conn);
  }
}
