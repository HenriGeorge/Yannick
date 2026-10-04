#!/usr/bin/env python3
# dependencies = []
"""WorktreeRemove hook — the safety net for worktree teardown, on the native event.

Before a worktree disappears: back up its untracked+ignored files and save uncommitted tracked
changes as an applyable patch under ~/.local/share/claude-template/backups/<repo>/<wt>-<ts>/,
then free the worktree's PORT reservation. WorktreeRemove is log-only (cannot block), so this
hook always exits 0 and reports what it saved. Fail-open on malformed input.
"""
import json
import os
import shutil
import subprocess
import sys
import time

BACKUP_ROOT = os.path.join(os.path.expanduser("~"), ".local", "share", "claude-template", "backups")
PORT_DIR = os.path.join(os.path.expanduser("~"), ".cache", "claude-template", "ports")


def _run(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


# G1 (plugin install hygiene spec, F1) — prune this worktree's plugin-install entries from
# installed_plugins.json so they don't pile up as DEAD entries. Exact-path match only (never a
# prefix match — a sibling "foo-bar" worktree must survive a "foo" removal). Never blocks
# (WorktreeRemove is log-only anyway); every failure path degrades to a stdout note, file untouched.
def _prune_plugin_installs(wt: str) -> None:
    plugins_dir = os.environ.get("CT_PLUGINS_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "plugins"
    )
    installed_path = os.path.join(plugins_dir, "installed_plugins.json")
    if not os.path.isfile(installed_path):
        return
    try:
        with open(installed_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        print("worktree_remove: could not prune plugin installs (unreadable file) — "
              "run claude-template plugin-doctor")
        return
    if data.get("version") != 2 or not isinstance(data.get("plugins"), dict):
        print("worktree_remove: could not prune plugin installs (unexpected shape) — "
              "run claude-template plugin-doctor")
        return

    target = os.path.realpath(wt)
    pruned = 0
    for key in list(data["plugins"]):
        entries = data["plugins"][key]
        if not isinstance(entries, list):
            continue
        kept = []
        for e in entries:
            p = e.get("projectPath")
            if e.get("scope") == "project" and p and os.path.realpath(p) == target:
                pruned += 1
                continue
            kept.append(e)
        if kept:
            data["plugins"][key] = kept
        else:
            del data["plugins"][key]

    if pruned == 0:
        return
    try:
        backup = installed_path + ".bak-wtremove"
        with open(installed_path, encoding="utf-8") as src, open(backup, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        tmp = installed_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, installed_path)
        with open(installed_path, encoding="utf-8") as f:
            json.load(f)  # re-read verify
    except (OSError, ValueError) as e:
        print(f"worktree_remove: could not prune plugin installs ({e}) — "
              "run claude-template plugin-doctor")
        return
    print(f"worktree_remove: pruned {pruned} plugin install entr{'y' if pruned == 1 else 'ies'} "
          f"for {wt}")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if payload.get("hook_event_name") != "WorktreeRemove":
        return
    wt = payload.get("worktree_path") or payload.get("path") or ""
    if not wt or not os.path.isdir(wt):
        return

    rc, common = _run(["git", "rev-parse", "--git-common-dir"], cwd=wt)
    repo = "unknown-repo"
    if rc == 0 and common.strip():
        repo = os.path.basename(os.path.dirname(os.path.abspath(os.path.join(wt, common.strip())))) or "unknown-repo"

    dest = os.path.join(BACKUP_ROOT, repo, f"{os.path.basename(wt)}-{int(time.time())}")
    saved = 0
    failed = 0

    # untracked + ignored files — a failed enumeration must NOT read as "nothing to back up":
    # the worktree is about to be deleted and these files have no other copy.
    rc, listing = _run(["git", "ls-files", "--others", "--exclude-standard", "--ignored",
                        "--directory"], cwd=wt)
    rc2, untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=wt)
    if rc != 0 or rc2 != 0:
        print("worktree_remove: WARN could not enumerate untracked files "
              f"(git rc={rc}/{rc2}) — backup may be INCOMPLETE")
    names = set()
    for blob in (listing, untracked):
        for line in blob.splitlines():
            line = line.strip().rstrip("/")
            if line:
                names.add(line)
    for rel in sorted(names):
        src = os.path.join(wt, rel)
        if not os.path.isfile(src):
            continue
        tgt = os.path.join(dest, rel)
        try:
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            shutil.copy2(src, tgt)
            saved += 1
        except OSError as e:
            failed += 1
            print(f"worktree_remove: WARN failed to back up {rel}: {e}")

    # uncommitted tracked changes -> patch. `git diff HEAD` (not bare `git diff`) so STAGED
    # but uncommitted work is captured too.
    rc, diff = _run(["git", "diff", "HEAD"], cwd=wt)
    if rc == 0 and diff.strip():
        try:
            os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, "uncommitted.patch"), "w", encoding="utf-8") as f:
                f.write(diff)
            saved += 1
        except OSError as e:
            failed += 1
            print(f"worktree_remove: WARN could not save uncommitted.patch: {e}")

    # free the PORT reservation
    env_path = os.path.join(wt, ".claude", "worktree.env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("PORT="):
                    port = line.split("=", 1)[1].strip()
                    res = os.path.join(PORT_DIR, f"{port}.port")
                    if os.path.isfile(res):
                        os.unlink(res)
    except OSError:
        pass

    tail = f" ({failed} FAILED)" if failed else ""
    if saved or failed:
        print(f"worktree_remove: backed up {saved} item(s){tail} → {dest}")
    else:
        print("worktree_remove: nothing to back up")

    # G1 — prune this worktree's plugin-install entries (after backup/PORT work, per the spec).
    _prune_plugin_installs(wt)


if __name__ == "__main__":
    main()
    sys.exit(0)
