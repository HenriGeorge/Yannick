# ctf-relay — ClaudeTalkToFigma WebSocket relay (loopback-patched)

The `:3055` relay that bridges the CLI figma-bridge scripts and the
**ClaudeTalkToFigma** Figma plugin (`../ctf-plugin/`).

## Files
- `socket.js` — vendored from `claude-talk-to-figma-mcp@1.0.0` (`dist/socket.js`),
  with one change: the Bun server binds **`hostname: "127.0.0.1"`** instead of the
  upstream default `0.0.0.0`. Loopback-only, not LAN-exposed.
- `start-relay.sh` — launcher; runs `socket.js` under `bun`, refuses to double-start.

## Run
```bash
setsid ./start-relay.sh &          # detached background
curl -s http://127.0.0.1:3055/status   # health check
```

## Requirements / notes
- Needs **bun** (`curl -fsSL https://bun.sh/install | bash`). The upstream bin is a
  Bun program with no node shebang, so node/`npx …-socket` cannot run it.
- The repo's own autolaunch (`figma-bridge/.../ctf-autolaunch.mjs`) is macOS-only
  (osascript) and shells out to `npx …-socket`; on WSL2/Linux use this script instead.
- **WSL2 connectivity (important):** Figma runs on the Windows side and connects to
  `ws://localhost:3055`. Whether the `127.0.0.1` bind is reachable from the Windows
  host depends on the WSL2 networking mode: in **mirrored** mode loopback is shared and
  it works; in the default **NAT** mode `localhostForwarding` *usually* reaches it, but
  it is **not guaranteed** — upstream's own inline comment in `socket.js` recommends
  `0.0.0.0` "to allow connections in windows wsl". If the plugin cannot connect, change
  `hostname` in `socket.js` to `0.0.0.0`. In NAT mode the WSL VM sits behind Windows NAT,
  so `0.0.0.0` is host-reachable but still not directly LAN-exposed (external LAN access
  would require an explicit `netsh portproxy`); on native Linux `0.0.0.0` *is* LAN-exposed,
  so firewall `:3055` there. Check your mode with `wslinfo --networking-mode`.
- Not a service — does not survive reboot. Re-run `start-relay.sh` to bring it back.

## Re-vendoring
To refresh `socket.js` from a newer upstream, re-copy its `dist/socket.js` and re-apply
the one-line patch: add `hostname: "127.0.0.1",` immediately after `port: 3055,` in the
`Bun.serve({ ... })` call.
