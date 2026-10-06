#!/usr/bin/env python3
# dependencies = []
"""SessionStart hook — opt-in Figma design-environment launcher (async; never blocks startup).

Fires ONLY when ALL of: source == "startup" (self-filtered here, not via settings matchers),
platform is macOS or Linux, and the project's .claude/worktrees.conf contains an uncommented
FIGMA_LAUNCH=1. Then: opens Figma (`open -a Figma` on macOS; `xdg-open` of the Figma URL on
Linux — Figma has no native Linux app, so the browser is the target) with the file URL
https://www.figma.com/design/<FIGMA_FILE_KEY> when the key is set and charset-valid, and
detach-spawns the ClaudeTalkToFigma websocket bridge via npx IF nothing is already listening
on the bridge port. The bundled bridge hardcodes :3055 (no port flag or env), so the port is
fixed — probe and spawn always agree on 3055, which keeps the spawn idempotent across restarts.

SECURITY (issue #305): the bridge runs Bun.serve({port:3055}) with NO hostname, so Bun binds
0.0.0.0 — the socket is LAN-reachable and unauthenticated, and upstream exposes NO flag/env to
restrict the interface (confirmed by reading dist/socket.js — lesson #246). We cannot rebind it
from the spawn, so the tightest mitigation is a loud LAN-exposure warning on every spawn (see
_BIND_WARNING) plus the caveat in docs/workflow/HOOKS.md. Firewall :3055 or stay on a trusted network.

Security posture (spec grill findings): the conf is repo-tracked, so NOTHING from it is ever
shell-interpreted — the spawn command is hardcoded, FIGMA_FILE_KEY is validated [A-Za-z0-9]+,
and all spawns are argv-style (no shell). Fail-open and silent on any
error (no Figma installed, no conf, probe failure); the only observability is a best-effort
breadcrumb log at ~/.local/share/claude-template/figma-launch.log.
"""
import datetime
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

BRIDGE_PACKAGE = "claude-talk-to-figma-mcp@latest"
BRIDGE_BIN = "claude-talk-to-figma-mcp-socket"
DEFAULT_PORT = 3055
# The patched ClaudeTalkToFigma plugin panel is vendored in claude-template-core. Figma Desktop
# registers a dev plugin by ABSOLUTE path, but the plugin cache dir is version-keyed (changes on every
# bump) — so we mirror the vendored panel to a STABLE per-machine path the human imports once (#830).
_CTF_STABLE_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "claude-template", "ctf-plugin")
_CTF_FILES = ("manifest.json", "code.js", "ui.html", "setcharacters.js", "LICENSE", "VENDOR.md")
# CT_FIGMA_PROBE_PORT overrides ONLY the "already listening?" probe port, for hermetic tests.
# It never reaches the spawned bridge (which always binds 3055) — production has no port knob.
_PROBE_PORT_ENV = "CT_FIGMA_PROBE_PORT"
# The bundled bridge hardcodes Bun.serve({port:3055}) with no hostname → Bun binds 0.0.0.0,
# so the socket is LAN-exposed and unauthenticated, with NO flag/env/port override to restrict it
# (confirmed by reading dist/socket.js — lesson #246, issue #305). We cannot rebind it from the
# spawn; the tightest mitigation is to surface the exposure loudly on every spawn.
_BIND_WARNING = (
    "WARNING: bridge binds 0.0.0.0:3055 (LAN-exposed, unauthenticated) — upstream has no "
    "loopback/port override. Firewall :3055 or run only on a trusted network. See docs/workflow/HOOKS.md."
)

_CONF_LINE = re.compile(r"""^\s*([A-Z_][A-Z0-9_]*)=("([^"]*)"|'([^']*)'|([^#\s]*))""")

# --- plugin auto-launch (macOS only) -------------------------------------------------------------
# After Figma + the bridge are up, drive the Figma UI (Cmd+P → ClaudeTalkToFigma → Enter) to run the
# plugin, verify it joined the folder channel via the figma-bridge `probe` CLI, and grab a region shot
# of the Figma window. This is macOS-only (Linux has no Figma app) and gated three ways so a misfired
# keystroke can NEVER blindly edit the user's design file: (1) opt-out FIGMA_AUTOLAUNCH_PLUGIN=0;
# (2) an import sentinel — inert until the human imports the dev plugin once and touches the sentinel;
# (3) the probe is the ONLY source of truth (keystrokes are capped, never trusted, never hammered).
# The one-time import step is the SAME manual gesture Figma requires to register a dev plugin, so the
# automation cannot run before it. Fail-open + breadcrumbs, like the rest of the hook.
_CTF_IMPORTED_SENTINEL = os.path.join(os.path.expanduser("~"), ".local", "share", "claude-template", "ctf-imported")
# Test-only knobs (never set in production, like CT_FIGMA_PROBE_PORT):
#   CT_FIGMA_PROBE_CMD    — a probe executable the suite controls (prints the probe JSON) instead of
#                           locating + running figma.mjs against a live relay.
#   CT_FIGMA_AUTOLAUNCH_FAST=1 — collapse the readiness timeout / probe-poll / sleeps so the GUI-gate
#                           logic runs hermetically fast under mocked osascript/screencapture.
_PROBE_CMD_ENV = "CT_FIGMA_PROBE_CMD"
_FAST = os.environ.get("CT_FIGMA_AUTOLAUNCH_FAST") == "1"
_KEYSTROKE_CAP = 2
_READY_TIMEOUT = 2 if _FAST else 20
_PROBE_POLL_TRIES = 1 if _FAST else 10
_POLL_SLEEP = 0.0 if _FAST else 1.0
# The Cmd+P plugin-run sequence. Escape FIRST (key code 53) exits any text-edit/rename mode and clears
# the selection, so if Cmd+P fails to open Quick Actions the follow-up typing cannot land in the canvas.
# key code 36 = Return (runs the highlighted Quick-Actions result).
_KEYSTROKE_SCRIPT = (
    'tell application "System Events"\n'
    "key code 53\n"
    "delay 0.3\n"
    'keystroke "p" using command down\n'
    "delay 0.6\n"
    'keystroke "ClaudeTalkToFigma"\n'
    "delay 0.6\n"
    "key code 36\n"
    "end tell"
)


def _osa(script: str, timeout: int = 10):
    # TimeoutExpired / FileNotFoundError → None (mirrors the node twin returning null on r.error), so
    # _figma_ready funnels a timed-out osascript to "notfront", NOT the wrong "tcc"/Accessibility path.
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except Exception as e:
        _log(f"osascript failed: {e}")
        return None


def _find_figma_cli(project: str):
    # Locate the figma-bridge CLI (figma.mjs) the same way _find_ctf_src locates the vendored panel:
    # prefer a repo-local core-plugin copy, else the newest match in the version-keyed plugin cache.
    cand = os.path.join(project, "plugins", "claude-template-core", "skills", "figma-bridge",
                        "scripts", "figma", "figma.mjs")
    if os.path.isfile(cand):
        return cand
    roots = [os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache")]
    pr = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if pr:
        roots.append(os.path.dirname(os.path.dirname(os.path.dirname(pr))))
    hits = []
    for root in roots:
        if root and os.path.isdir(root):
            hits += glob.glob(os.path.join(root, "*", "claude-template-core", "*", "skills",
                                           "figma-bridge", "scripts", "figma", "figma.mjs"))
    if not hits:
        return None
    hits.sort(key=os.path.getmtime, reverse=True)
    return hits[0]


def _probe_connected(project: str, channel: str):
    # Returns True (plugin joined the channel), False (not joined), or None (couldn't probe).
    override = os.environ.get(_PROBE_CMD_ENV, "")
    if override:
        cmd = [override, f"--channel={channel}"]
    else:
        cli = _find_figma_cli(project)
        if not cli:
            _log("probe skipped: figma-bridge CLI (figma.mjs) not found")
            return None
        cmd = ["node", cli, "probe", f"--channel={channel}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    except Exception as e:
        _log(f"probe failed: {e}")
        return None
    try:
        data = json.loads(r.stdout or "[]")
        return any(isinstance(x, dict) and x.get("status") == "CONNECTED" for x in data)
    except Exception as e:
        _log(f"probe parse failed: {e}")
        return None


def _discover_channel(project: str):
    # Learn the live channel from the bridge CLI's /status-backed discovery (probe with NO --channel,
    # which self-discovers from the relay). Returns the first CONNECTED channel name, or None → the
    # caller keeps the folder-channel default (so a renamed Figma file no longer strands on the folder).
    override = os.environ.get(_PROBE_CMD_ENV, "")
    if override:
        cmd = [override]
    else:
        cli = _find_figma_cli(project)
        if not cli:
            return None
        cmd = ["node", cli, "probe"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
        data = json.loads(r.stdout or "[]")
    except Exception as e:
        _log(f"discover failed: {e}")
        return None
    for x in data if isinstance(data, list) else []:
        if isinstance(x, dict) and x.get("status") == "CONNECTED" and x.get("channel"):
            return x["channel"]
    return None


def _poll_connected(project: str, channel: str) -> bool:
    for _ in range(_PROBE_POLL_TRIES):
        if _probe_connected(project, channel):
            return True
        time.sleep(_POLL_SLEEP)
    return False


def _figma_ready() -> str:
    # "ready" (Figma frontmost) | "tcc" (System Events control denied) | "notfront" (never frontmost).
    deadline = time.monotonic() + _READY_TIMEOUT
    first = True
    while first or time.monotonic() < deadline:
        first = False
        _osa('tell application "Figma" to activate')
        r = _osa('tell application "System Events" to get name of first application process whose frontmost is true')
        if r is None:
            return "notfront"
        if r.returncode != 0:
            return "tcc"
        if (r.stdout or "").strip() == "Figma":
            return "ready"
        time.sleep(_POLL_SLEEP)
    return "notfront"


# A Figma window shorter than this is a utility sliver (e.g. the ~39px "window 1"), never the canvas.
_MIN_WINDOW_H = 100


def _screenshot(channel: str):
    # Region-scoped grab of the Figma CANVAS (NEVER full-screen — privacy). Enumerate EVERY Figma window
    # and pick the largest-area one, skipping the ~39px utility sliver that is window 1 — grabbing window
    # 1 captured only that sliver (#871). `screencapture -R` needs no CG window id. Needs macOS Screen
    # Recording — on denial screencapture errors / writes nothing, so warn + skip. Returns the path or None.
    r = _osa('tell application "System Events" to tell process "Figma"\n'
             'set out to ""\n'
             'repeat with w in windows\n'
             'set p to position of w\n'
             'set s to size of w\n'
             'set out to out & (item 1 of p) & "," & (item 2 of p) & "," & '
             '(item 1 of s) & "," & (item 2 of s) & linefeed\n'
             'end repeat\n'
             'return out\n'
             'end tell')
    if r is None or r.returncode != 0 or not (r.stdout or "").strip():
        _log("screenshot skipped: could not read Figma window bounds")
        return None
    nums = [int(n) for n in re.findall(r"-?\d+", r.stdout)]
    wins = [nums[i:i + 4] for i in range(0, len(nums) - len(nums) % 4, 4)]
    if not wins:
        _log("screenshot skipped: unexpected window bounds")
        return None
    usable = [win for win in wins if win[3] > _MIN_WINDOW_H]
    if len(usable) < len(wins):
        _log(f"screenshot: skipped {len(wins) - len(usable)} degenerate window(s) (height<={_MIN_WINDOW_H})")
    x, y, w, h = max(usable or wins, key=lambda win: win[2] * win[3])
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", channel) or "figma"
    d = os.path.join(os.path.expanduser("~"), ".local", "share", "claude-template")
    try:
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, f"figma-launch-{safe}.png")
        cr = subprocess.run(["screencapture", "-x", f"-R{x},{y},{w},{h}", out],
                            capture_output=True, text=True, timeout=15, check=False)
        if cr.returncode != 0 or not os.path.isfile(out):
            _log(f"screenshot failed (Screen Recording permission?): rc={cr.returncode}")
            return None
        return out
    except Exception as e:
        _log(f"screenshot failed: {e}")
        return None


def _autolaunch_plugin(platform: str, conf: dict, project: str, channel: str) -> None:
    if platform != "darwin":
        return
    if conf.get("FIGMA_AUTOLAUNCH_PLUGIN", "1") == "0":
        return
    if not os.path.isfile(_CTF_IMPORTED_SENTINEL):
        print("Figma plugin auto-launch skipped — import the panel once (Figma › Plugins › Development "
              f"› Import plugin from manifest), then run: touch {_CTF_IMPORTED_SENTINEL}")
        return
    ready = _figma_ready()
    if ready == "tcc":
        print("Figma plugin auto-launch skipped — grant Accessibility to your terminal "
              "(System Settings › Privacy & Security › Accessibility), then restart the session.")
        return
    if ready != "ready":
        print("Figma plugin auto-launch skipped — Figma did not come to the front in time. "
              f"Run it manually: Cmd+P › ClaudeTalkToFigma › channel '{channel}'.")
        return
    discovered = _discover_channel(project)
    if discovered:
        channel = discovered  # use the live open-file channel, not the folder-name guess
    connected = _probe_connected(project, channel)
    attempts = 0
    while not connected and attempts < _KEYSTROKE_CAP:
        _osa(_KEYSTROKE_SCRIPT, timeout=15)
        attempts += 1
        connected = _poll_connected(project, channel)
    if not connected:
        print(f"Figma plugin not connected on channel '{channel}' after {attempts} attempt(s) — "
              "run manually: Cmd+P › ClaudeTalkToFigma › enter the channel.")
        return
    print(f"Figma plugin connected on channel: {channel}")
    shot = _screenshot(channel)
    if shot:
        print(f"Figma screenshot: {shot}")


def _log(msg: str) -> None:
    try:
        d = os.path.join(os.path.expanduser("~"), ".local", "share", "claude-template")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "figma-launch.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def _folder_channel(project: str) -> str:
    # The bridge channel the ClaudeTalkToFigma plugin panel expects = the project folder name, matching
    # channel-resolve.mjs folderChannel(): basename of the MAIN checkout (git-common-dir's parent), so it
    # is identical across every worktree. `git -C project` because the hook's cwd is not the project.
    try:
        out = subprocess.run(
            ["git", "-C", project, "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        common = out if os.path.isabs(out) else os.path.join(project, out)
        return os.path.basename(os.path.dirname(os.path.realpath(common)))
    except Exception:
        return os.path.basename(os.path.realpath(project))


def _find_ctf_src(project: str):
    # Locate the vendored ctf-plugin dir. Prefer a repo-local copy (the template itself, or a repo that
    # vendored via propagate); else the newest match in the version-keyed plugin marketplace cache.
    cand = os.path.join(project, "plugins", "claude-template-core", "vendor", "ctf-plugin", "manifest.json")
    if os.path.isfile(cand):
        return os.path.dirname(cand)
    roots = [os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache")]
    pr = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if pr:
        roots.append(os.path.dirname(os.path.dirname(os.path.dirname(pr))))
    hits = []
    for root in roots:
        if root and os.path.isdir(root):
            hits += glob.glob(os.path.join(root, "*", "claude-template-core", "*", "vendor", "ctf-plugin", "manifest.json"))
    if not hits:
        return None
    hits.sort(key=os.path.getmtime, reverse=True)
    return os.path.dirname(hits[0])


def _mirror_ctf_plugin(project: str):
    # Copy the vendored panel to a stable path so Figma's absolute-path dev-import survives version bumps.
    # _find_ctf_src is inside the try so a file-vanish race in its mtime sort leaves a breadcrumb rather
    # than propagating out and silently aborting the rest of the hook.
    try:
        src = _find_ctf_src(project)
        if not src:
            return None
        os.makedirs(_CTF_STABLE_DIR, exist_ok=True)
        for fn in _CTF_FILES:
            s = os.path.join(src, fn)
            if os.path.isfile(s):
                shutil.copy2(s, os.path.join(_CTF_STABLE_DIR, fn))
        return os.path.join(_CTF_STABLE_DIR, "manifest.json")
    except Exception as e:
        _log(f"ctf-plugin mirror failed: {e}")
        return None


def _read_conf(path: str) -> dict:
    conf = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _CONF_LINE.match(line)
            if m:
                conf[m.group(1)] = m.group(3) or m.group(4) or m.group(5) or ""
    return conf


def _port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict) or payload.get("source") != "startup":
        return 0
    if sys.platform == "darwin":
        _platform = "darwin"
    elif sys.platform.startswith("linux"):
        _platform = "linux"
    else:
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    conf_path = os.path.join(project, ".claude", "worktrees.conf")
    if not os.path.isfile(conf_path):
        return 0
    try:
        conf = _read_conf(conf_path)
    except Exception:
        _log(f"could not read {conf_path} — skipping")
        return 0
    if conf.get("FIGMA_LAUNCH") != "1":
        return 0

    # Echo the bridge channel (folder-name default) to stdout so the human sees exactly what to type
    # into the ClaudeTalkToFigma plugin panel (issue #830). SessionStart surfaces stdout as context.
    channel = _folder_channel(project)
    print(f"Bridge channel: {channel}")

    # Mirror the vendored (patched) ClaudeTalkToFigma panel to a stable path and tell the human where to
    # import it once. Fail-open: if the vendored dir can't be found, skip silently.
    manifest = _mirror_ctf_plugin(project)
    if manifest:
        print(f"Figma plugin (import once › Figma › Plugins › Development › Import plugin from manifest): {manifest}")

    # open Figma (macOS) or Figma in browser (Linux) — with the project file when a well-formed key is configured
    key = conf.get("FIGMA_FILE_KEY", "")
    valid_key = bool(re.fullmatch(r"[A-Za-z0-9]+", key or ""))
    if key and not valid_key:
        _log(f"ignoring malformed FIGMA_FILE_KEY={key!r}; opening {'bare Figma' if _platform == 'darwin' else 'https://www.figma.com'}")
    if _platform == "darwin":
        open_cmd = ["open", "-a", "Figma"]
        if valid_key:
            open_cmd.append(f"https://www.figma.com/design/{key}")
    else:  # linux
        url = f"https://www.figma.com/design/{key}" if valid_key else "https://www.figma.com"
        open_cmd = ["xdg-open", url]
    try:
        subprocess.run(open_cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15, check=False)
        _log(f"opened: {' '.join(open_cmd)}")
    except Exception:
        _log(f"{'open -a Figma' if _platform == 'darwin' else 'xdg-open'} failed (app missing?) — continuing")

    # bridge — idempotent: only spawn when the fixed bridge port (3055) is silent.
    # The env override is test-only (see _PROBE_PORT_ENV); production always probes 3055.
    probe_raw = os.environ.get(_PROBE_PORT_ENV, "")
    port = int(probe_raw) if re.fullmatch(r"[0-9]{1,5}", probe_raw) and 1 <= int(probe_raw) <= 65535 else DEFAULT_PORT
    if _port_listening(port):
        _log(f"bridge already listening on :{port} — no spawn")
    else:
        _log(_BIND_WARNING)
        try:
            d = os.path.join(os.path.expanduser("~"), ".local", "share", "claude-template")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "figma-launch.log"), "ab") as logf:
                subprocess.Popen(
                    ["npx", f"--package={BRIDGE_PACKAGE}", BRIDGE_BIN],
                    stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                    start_new_session=True,
                )
            _log(f"bridge spawn: npx --package={BRIDGE_PACKAGE} {BRIDGE_BIN} (port :{port} was silent)")
        except Exception as e:
            _log(f"bridge spawn failed: {e}")

    # macOS-only: drive the Figma UI to run the plugin, verify the channel, screenshot. Gated + fail-open.
    _autolaunch_plugin(_platform, conf, project, channel)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
