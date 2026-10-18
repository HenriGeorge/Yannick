#!/usr/bin/env bash
# start-relay.sh — launch the ClaudeTalkToFigma WebSocket relay bound to 127.0.0.1:3055.
#
# Why this exists: upstream ships the relay (`claude-talk-to-figma-mcp-socket`) as a Bun
# program with no node shebang, and defaults its bind to 0.0.0.0 (LAN-exposed). On a
# Bun-less box (e.g. WSL2) `npx …-socket` fails, and the repo's osascript autolaunch is
# macOS-only. This runs the vendored, loopback-patched copy under bun instead.
#
# Usage:  ./start-relay.sh            # foreground
#         setsid ./start-relay.sh &   # detached background
set -euo pipefail

PORT=3055
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOCKET="$HERE/socket.js"

if command -v bun >/dev/null 2>&1; then
  BUN="$(command -v bun)"
elif [ -x "$HOME/.bun/bin/bun" ]; then
  BUN="$HOME/.bun/bin/bun"
else
  echo "error: bun not found. Install it: curl -fsSL https://bun.sh/install | bash" >&2
  exit 1
fi

[ -f "$SOCKET" ] || { echo "error: missing $SOCKET" >&2; exit 1; }

if (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q ":$PORT "; then
  echo "relay already listening on :$PORT — nothing to do"
  exit 0
fi

echo "starting ClaudeTalkToFigma relay on 127.0.0.1:$PORT (bun: $BUN)"
exec "$BUN" "$SOCKET"
