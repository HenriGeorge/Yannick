#!/usr/bin/env python3
# dependencies = []
"""WorktreeCreate hook — CREATE and provision a native worktree.

Spec: docs/superpowers/specs/2026-08-14-hooks-native-worktrees-design.md.

Contract (observed from the real harness payload):
  Input JSON on stdin: {"hook_event_name":"WorktreeCreate", "name":<str>, "cwd":<str>, ...}.
  The harness does NOT pre-create the worktree and passes NO path — only `name`. A registered
  WorktreeCreate command hook OWNS creation and MUST echo the new worktree's absolute path on
  stdout (that path is what the harness switches the session into). All diagnostics go to stderr
  so they never corrupt the single stdout path line.

  Back-compat: if the payload DOES carry an existing `worktree_path`/`path` (older harness, tests),
  that dir is provisioned in place and echoed — no creation.

Steps after the worktree exists (each independent; network steps warn-and-continue per grill G8):
  1. `git fetch origin` in the primary checkout (warn on failure — offline is fine).
  2. WARN (never block) if the worktree's HEAD is behind origin/<default> — GATE-0 signal.
  3. Copy gitignored `.env*` files from the primary checkout into the worktree (idempotent).
  4. If the repo's worktrees.conf says SETUP=npm, run `npm install --prefer-offline` (warn-only).
  5. Allocate a free PORT (reservation files under ~/.cache/claude-template/ports/, TTL 90s) and
     write it to <worktree>/.claude/worktree.env (kept if already present — idempotent).

WorktreeCreate is a blocking event. This hook exits 0 on success (creation + provisioning; the
network-dependent provisioning steps warn-and-continue). It exits NON-ZERO — writing a one-line
reason to stderr, never a silent empty-stdout exit 0 — when creation fails (both the `-b` add and
the `--detach` fallback) OR the payload is unusable (malformed JSON, a back-compat path that does
not exist, a missing name/primary). The opaque "returned no worktree path" harness error was
exactly that silent exit-0 path (issue #927). A non-WorktreeCreate event passes through (exit 0).
"""
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import time

try:
    from _telemetry_gate import telemetry_enabled
except Exception:  # noqa: BLE001 - degrade to enabled if the helper is missing
    def telemetry_enabled(_="."):  # type: ignore
        return True

PORT_DIR = os.path.join(os.path.expanduser("~"), ".cache", "claude-template", "ports")
PORT_TTL = 90
PORT_BASE = 3000


def _warn(msg: str) -> None:
    # diagnostics ONLY to stderr — stdout is reserved for the single worktree-path line.
    print(f"worktree_create: {msg}", file=sys.stderr)


def _emit_telemetry(primary: str, name: str, decision: str) -> None:
    """One metadata row per create to .claude/telemetry/hook-events.jsonl (issue #927).

    `decision` is "create" (on its branch), "detached" (fallback) or "error". Best-effort and
    opt-out-aware: WorktreeCreate wrote NO telemetry, so a parallel-create failure left no trace.
    Any error here is swallowed — telemetry must never break creation.
    """
    try:
        project_dir = primary or "."
        if not telemetry_enabled(project_dir):
            return
        row = {
            "ts": int(time.time()),
            "event": "WorktreeCreate",
            "hook": "worktree_create.py",
            "exit": 1 if decision == "error" else 0,
            "decision": decision,
            "name": name,
        }
        out_dir = os.path.join(project_dir, ".claude", "telemetry")
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "hook-events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:  # noqa: BLE001 - never let telemetry wedge worktree creation
        pass


def _run(args: list[str], cwd: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=120)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # timeout, missing binary — warn-and-continue territory
        return 1, str(e)


def _conf_val(primary: str, key: str) -> str | None:
    path = os.path.join(primary, ".claude", "worktrees.conf")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or None
    except OSError:
        pass
    return None


def _primary_checkout(cwd: str) -> str:
    """The main checkout for `cwd`, whether cwd is the primary or a linked worktree."""
    if not cwd:
        return ""
    rc, common = _run(["git", "rev-parse", "--git-common-dir"], cwd=cwd)
    if rc == 0 and common:
        cand = os.path.dirname(os.path.abspath(os.path.join(cwd, common)))
        if os.path.isdir(cand):
            return cand
    return cwd if os.path.isdir(cwd) else ""


def _baseref_mode(primary: str) -> str:
    """`worktree.baseRef` from project then user settings.json — 'fresh' (default) or 'head'."""
    candidates = [
        os.path.join(primary, ".claude", "settings.json"),
        os.path.join(primary, ".claude", "settings.local.json"),
        os.path.join(os.path.expanduser("~"), ".claude", "settings.json"),
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f).get("worktree", {})
            val = cfg.get("baseRef") if isinstance(cfg, dict) else None
        except (OSError, ValueError, AttributeError):
            continue
        if val:
            return str(val)
    return "fresh"


def _base_ref(primary: str) -> str:
    """Resolve the ref a new worktree branches from. fresh → origin/<default>; head/offline → HEAD."""
    if _baseref_mode(primary) != "head":
        rc, default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=primary)
        if rc == 0 and default:
            return default  # e.g. "origin/main"
    return "HEAD"


def _create_worktree(primary: str, wt: str, name: str) -> str:
    """`git worktree add` at `wt` on branch `name`; fall back to detached.

    Returns "create" (on its branch), "detached" (fallback at the base ref) or "failed".
    """
    try:
        os.makedirs(os.path.dirname(wt), exist_ok=True)
    except OSError as e:
        _warn(f"WARN could not create worktrees dir: {e}")
        return "failed"
    base = _base_ref(primary)
    # --no-track: when `base` is a remote-tracking ref (origin/<default>), a plain `-b` writes
    # branch.<name>.remote/merge into the SHARED .git/config, and parallel creates race on
    # .git/config.lock — the loser's config write fails and the whole add aborts (issue #927).
    # Agent branches tracking origin/<default> is a footgun anyway (a `git pull` pulls main).
    rc, out = _run(["git", "worktree", "add", "--no-track", "-b", name, wt, base], cwd=primary)
    if rc == 0:
        return "create"
    # branch `name` may already exist, or `base` is unfetched (offline) — try detached at base.
    rc2, out2 = _run(["git", "worktree", "add", "--detach", wt, base], cwd=primary)
    if rc2 == 0:
        # Surface the FULL `-b` output (not just splitlines()[0], the useless "Preparing worktree"),
        # so the real reason the branch was unavailable is visible — a detached HEAD instead of the
        # named branch is a silent degradation worth diagnosing (issue #927 fix-round).
        _warn(f"WARN created DETACHED worktree — branch '{name}' unavailable, the -b add said:")
        _warn(out or "unknown")
        return "detached"
    # Both adds failed. Surface BOTH git outputs IN FULL (not just the first line, which is the
    # useless "Preparing worktree …") so the harness shows the real cause instead of the opaque
    # "returned no worktree path" (issue #927). main() exits non-zero on this return.
    _warn(f"ERROR worktree add failed for '{name}':")
    _warn(f"  -b:      {out or 'unknown'}")
    _warn(f"  --detach: {out2 or 'unknown'}")
    return "failed"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _reserved_ports() -> set[int]:
    now = time.time()
    out: set[int] = set()
    for f in glob.glob(os.path.join(PORT_DIR, "*.port")):
        try:
            if now - os.path.getmtime(f) > PORT_TTL:
                os.unlink(f)
                continue
            out.add(int(os.path.basename(f).split(".")[0]))
        except (OSError, ValueError):
            continue
    return out


def _allocate_port() -> int | None:
    # best-effort throughout: WorktreeCreate is a BLOCKING event, so an unexpected filesystem
    # error (read-only ~/.cache, ENOSPC) must degrade to the caller's "WARN no free port" path,
    # never crash the hook and wedge worktree creation. Broad OSError is deliberate — the .cjs
    # twin's catch{} has the same width.
    try:
        os.makedirs(PORT_DIR, exist_ok=True)
    except OSError:
        return None
    taken = _reserved_ports()
    for port in range(PORT_BASE, PORT_BASE + 500):
        if port in taken or not _port_free(port):
            continue
        try:
            with open(os.path.join(PORT_DIR, f"{port}.port"), "x", encoding="utf-8") as f:
                f.write(f"pid={os.getpid()} ts={int(time.time())}\n")
            return port
        except OSError:
            continue
    return None


def _provision(primary: str, wt: str) -> None:
    """fetch → behind-check → env carry-in → npm → PORT. Every message goes to stderr."""
    # 1. fetch (warn-and-continue — G8)
    rc, out = _run(["git", "fetch", "origin"], cwd=primary or wt)
    if rc != 0:
        _warn(f"WARN fetch failed (offline?): {out.splitlines()[0] if out else 'unknown'}")

    # 2. behind-check vs origin/<default> (warn only)
    rc, default = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=wt)
    if rc == 0 and default:
        rc, behind = _run(["git", "rev-list", "--count", f"HEAD..{default}"], cwd=wt)
        if rc == 0 and behind.isdigit() and int(behind) > 0:
            _warn(f"WARN base is {behind} commits behind {default} — rebase before building (GATE 0)")

    # 3. env carry-in (idempotent overwrite)
    if primary and os.path.isdir(primary):
        for src in glob.glob(os.path.join(primary, ".env")) + glob.glob(os.path.join(primary, ".env.*")):
            try:
                shutil.copy2(src, os.path.join(wt, os.path.basename(src)))
            except OSError as e:
                _warn(f"WARN could not copy {os.path.basename(src)}: {e}")

    # 4. setup hook (warn-and-continue)
    if primary and _conf_val(primary, "SETUP") == "npm":
        rc, out = _run(["npm", "install", "--prefer-offline"], cwd=wt)
        if rc != 0:
            _warn("WARN npm install failed — run it manually")

    # 5. PORT (idempotent: keep an existing assignment)
    env_path = os.path.join(wt, ".claude", "worktree.env")
    try:
        with open(env_path, encoding="utf-8") as f:
            has_port = "PORT=" in f.read()
    except OSError:
        has_port = False
    if not has_port:
        port = _allocate_port()
        if port:
            os.makedirs(os.path.dirname(env_path), exist_ok=True)
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"PORT={port}\n")
            _warn(f"PORT={port} → .claude/worktree.env")
        else:
            _warn("WARN no free port found in range")


def main() -> int:
    # Every UNUSABLE-payload path writes a one-line reason to stderr and returns NON-ZERO — never a
    # silent exit 0 with empty stdout, which the harness reports as the opaque "returned no worktree
    # path" (issue #927 fix-round). The one exception is a non-WorktreeCreate event: that is a
    # legitimately-other event routed here, so it passes through as a silent exit 0.
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        _warn("ERROR malformed JSON on stdin")
        return 1
    if payload.get("hook_event_name") != "WorktreeCreate":
        return 0  # not our event — pass through silently

    primary = _primary_checkout(payload.get("cwd") or "")

    # Back-compat: an explicit path means the worktree already exists (older harness / tests).
    wt = payload.get("worktree_path") or payload.get("path") or ""
    if wt:
        if not os.path.isdir(wt):
            _warn(f"ERROR worktree_path given but does not exist: {wt}")
            return 1
    else:
        # Real harness contract: create the worktree from `name` and return its path.
        name = payload.get("name") or ""
        if not name or not primary:
            _warn("ERROR unusable payload: missing 'name' or could not resolve primary checkout")
            return 1
        wt = os.path.join(primary, ".claude", "worktrees", name)
        if not os.path.isdir(wt):
            status = _create_worktree(primary, wt, name)
            if status == "failed":
                # NEVER exit 0 with empty stdout — the opaque "returned no worktree path" (#927).
                # _create_worktree already surfaced git's real error.
                _emit_telemetry(primary, name, "error")
                return 1
            _emit_telemetry(primary, name, status)  # "create" or "detached"

    if not primary:
        _warn("WARN could not locate primary checkout — skipped .env* carry-in")

    _provision(primary, wt)

    # command-hook contract: the worktree path is the ONLY thing on stdout.
    print(wt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
