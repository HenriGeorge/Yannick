// preflight.mjs — relay-health check (design grill Q3 / spec O11). The dispatcher runs this before any
// RUN subcommand: the ClaudeTalkToFigma relay is known to wedge, so silence must be LEGIBLE — a clear
// cross-platform "run the plugin (Command+P)" message, never a raw ECONNREFUSED/socket stack. Replaces
// the deleted macOS-only auto-restart from figma-place with a portable, bounded reachability probe.
import { connect, close } from "./relay-client.mjs";

// assertRelay(socketUrl) — bounded (≤2s) connect attempt; throws a legible Error on silence.
export async function assertRelay(socketUrl, { timeoutMs = 2000 } = {}) {
  try {
    const conn = await connect(socketUrl, { timeoutMs });
    close(conn);
  } catch {
    throw new Error(
      `relay not responding at ${socketUrl} — run the ClaudeTalkToFigma plugin (Figma Command+P) and retry`,
    );
  }
}
