// relay-client.mjs — the ONE WebSocket wire-protocol implementation for the ClaudeTalkToFigma relay
// (ws://localhost:3055). Every subcommand talks to Figma through this, so the framing lives in exactly
// one place (was copy-pasted ~6× across the source scripts).
//
// Protocol (reverse-engineered from the relay dist/socket.js + plugin code.js):
//   join:    {type:'join', channel, id}
//            → server replies {type:'system', message:{id, result:'Connected to channel: …'}}
//   command: {type:'message', channel, message:{id, command, params}}
//            → relay echoes it back to the sender as {type:'broadcast', message:{…command…}, sender:'You'} (ignore)
//            → plugin reply unicasts as {type:'broadcast', message:{id, result|error}, sender:'User'}
//
// Node ≥21 built-in global WebSocket — no `ws` dependency.
import { randomUUID } from "node:crypto";

const newId = () => randomUUID();

// connect(socketUrl) -> Promise<conn>. Resolves once the socket is OPEN; rejects on error/timeout so
// preflight and channel-resolve can treat "no relay" as a plain rejection, not an uncaught socket event.
export async function connect(socketUrl, { timeoutMs = 4000 } = {}) {
  const ws = new WebSocket(socketUrl);
  const pending = new Map(); // id -> {resolve, reject, timer}
  const conn = { ws, pending, channel: null };

  ws.addEventListener("message", (ev) => {
    let d;
    try {
      d = JSON.parse(typeof ev.data === "string" ? ev.data : ev.data.toString());
    } catch {
      return;
    }
    // Command responses (and our own echoes) arrive as broadcasts; join confirmations as `system`.
    if (d.type !== "broadcast" || d.sender === "You" || !d.message) return;
    const m = d.message;
    if (m.command) return; // our own command echo — ignore
    const p = m.id && pending.get(m.id);
    if (!p) return;
    clearTimeout(p.timer);
    pending.delete(m.id);
    if (m.error !== undefined) {
      p.reject(new Error(typeof m.error === "string" ? m.error : JSON.stringify(m.error)));
    } else {
      p.resolve(m.result);
    }
  });

  // A mid-session socket drop must reject in-flight rpcs immediately — otherwise each waits its full
  // timeout (up to 170s for set_svg) before failing. Drain `pending` on close/error. (Connect-phase
  // failures are handled by the once-listeners below; at that point `pending` is empty, so this no-ops.)
  const drain = (why) => {
    for (const [id, p] of pending) {
      clearTimeout(p.timer);
      pending.delete(id);
      p.reject(new Error(`relay connection ${why} while awaiting rpc ${id}`));
    }
  };
  ws.addEventListener("close", () => drain("closed"));
  ws.addEventListener("error", () => drain("errored"));

  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      try { ws.close(); } catch {}
      reject(new Error(`relay connect timeout (${timeoutMs}ms) at ${socketUrl}`));
    }, timeoutMs);
    ws.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
    ws.addEventListener("error", (e) => {
      clearTimeout(timer);
      reject(new Error(`relay socket error at ${socketUrl}: ${e?.message ?? e}`));
    }, { once: true });
  });

  return conn;
}

// join(conn, channel) — join a talk-to-figma channel. Fire-and-forget (the plugin's `system`
// confirmation is advisory; the first rpc() will surface a real failure).
export function join(conn, channel) {
  conn.channel = channel;
  conn.ws.send(JSON.stringify({ type: "join", channel, id: newId() }));
}

// rpc(conn, command, params) -> Promise<result> — send one command, resolve the reply matched by id.
export function rpc(conn, command, params = {}, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    const id = newId();
    const timer = setTimeout(() => {
      conn.pending.delete(id);
      reject(new Error(`timeout (${timeoutMs}ms) waiting for "${command}" response`));
    }, timeoutMs);
    conn.pending.set(id, { resolve, reject, timer });
    conn.ws.send(JSON.stringify({ type: "message", channel: conn.channel, message: { id, command, params } }));
  });
}

export function close(conn) {
  try { conn.ws.close(); } catch {}
}
