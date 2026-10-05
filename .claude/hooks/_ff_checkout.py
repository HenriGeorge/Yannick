#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Shared safe fast-forward primitive (#fleet-freshness). Guarded-sibling import: the plugin runs
hooks as `python3 .../hooks/<h>.py` so sys.path[0] is the hooks dir; importers guard the import."""
import json
import os
import subprocess
import sys


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except Exception:  # noqa: BLE001
        return False


def _lock_dir(primary):
    """The per-repo session-lock dir, keyed IDENTICALLY to session_start._session_lock_dir.

    CT_SESSION_DIR override wins; else ~/.local/share/claude-template/sessions/<key>, where the key
    is the realpath of the repo's git-common-dir (both sides realpath so a symlinked path — e.g.
    /tmp -> /private/tmp on macOS — keys to the same dir). (#924 MEDIUM: shared normalization.)"""
    override = os.environ.get("CT_SESSION_DIR")
    if override:
        return override
    common = _git(primary, "rev-parse", "--git-common-dir", timeout=3)
    if common and not os.path.isabs(common):
        common = os.path.join(os.path.abspath(primary), common)
    base = os.path.realpath(common) if common else os.path.realpath(primary)
    key = base.replace(os.sep, "-").strip("-") or "root"
    return os.path.join(os.path.expanduser("~/.local/share/claude-template/sessions"), key)


def _ancestor_pids():
    """The set of pids in THIS process's ancestry (self + the ppid chain). A session's own heartbeat
    lock is owned by an ancestor (the claude process spawns the hook / the pr-merge-recover helper),
    so a lock whose pid is in this set is 'self', never a peer — this is why $PPID alone was wrong
    (the Bash-tool wrapper shell sits between us and the claude process). Bounded walk; `ps` is POSIX
    and dependency-free. Fail-open: a `ps` failure just stops the walk."""
    pids = set()
    cur = os.getpid()
    for _ in range(64):
        pids.add(cur)
        try:
            out = subprocess.run(["ps", "-o", "ppid=", "-p", str(cur)],
                                 capture_output=True, text=True, timeout=3)
            parent = int((out.stdout or "").strip())
        except Exception:  # noqa: BLE001 — ps missing / odd output → stop walking
            sys.stderr.write(
                "fleet-freshness: ancestry walk failed — own session may read as peer\n")
            break
        if parent <= 1 or parent in pids:
            break
        cur = parent
    return pids


def _other_session_active(primary):
    """#924 — True iff ANOTHER live session is sitting ON the primary checkout.

    A lock is a PEER only when ALL hold: its pid is alive, its pid is NOT in this process's ancestry
    (our own session's lock is owned by an ancestor — never a peer), AND its recorded cwd realpath
    EQUALS the primary's realpath. A session in a DIFFERENT worktree keys the same per-repo lock dir
    but cannot collide with a ff of the primary, so (cwd != primary) must not block. Reads the SAME
    lock dir session_start writes. Fail-open: a read error → False (never blocks a ff); an
    EXISTING-yet-unreadable dir leaves a one-line breadcrumb (#924 MEDIUM)."""
    d = _lock_dir(primary)
    if not os.path.isdir(d):
        return False
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json")]
    except Exception:  # noqa: BLE001 — exists but unreadable
        sys.stderr.write(
            f"fleet-freshness: session-lock dir {d} exists but could not be read — proceeding\n")
        return False
    prim = os.path.realpath(primary)
    mine = _ancestor_pids()
    for name in names:
        try:
            with open(os.path.join(d, name)) as fh:
                rec = json.load(fh)
            pid = int(rec.get("pid"))
            cwd = rec.get("cwd") or ""
        except Exception:  # noqa: BLE001 — unreadable/mid-write lock: not evidence of a live peer
            sys.stderr.write(f"fleet-freshness: session lock {name} unreadable/corrupt — skipping it\n")
            continue
        if pid in mine or not _pid_alive(pid):
            continue
        if not cwd:
            # A live, non-ancestor lock with no recorded cwd: we can't prove it ISN'T on the primary,
            # so take the safe side and treat it as a peer (#924 LOW-MEDIUM).
            sys.stderr.write(
                f"fleet-freshness: session lock {name} has no cwd — treating as a peer (safe side)\n")
            return True
        if os.path.realpath(cwd) == prim:
            return True
    return False


def _git(cwd, *args, timeout=8, env=None):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True,
                           timeout=timeout, check=False, env=env)
    except Exception:  # noqa: BLE001 — fail open
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _main_worktree(cwd):
    """The repo's MAIN working tree (not a linked worktree): parent of --git-common-dir."""
    common = _git(cwd, "rev-parse", "--git-common-dir")
    if not common:
        return None
    common = os.path.join(cwd, common) if not os.path.isabs(common) else common
    # common dir is <main>/.git ; its parent is the main working tree
    return os.path.dirname(os.path.normpath(common)) or None


def _has_dotgit_ancestor(cwd):
    """True if a `.git` (dir OR file — a linked-worktree/submodule pointer) exists at cwd or any
    ancestor. A pure filesystem walk, NO git — so it still answers when git itself is the failure
    (safe.directory refusal, git missing, a timeout). Distinguishes 'not a repo' from 'a repo whose
    git-common-dir lookup failed' (#924 MEDIUM)."""
    try:
        d = os.path.abspath(cwd or ".")
    except Exception:  # noqa: BLE001
        return False
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def _trunk(path):
    """Resolve the default branch short-name (mirrors pr_gate._trunk_ref)."""
    ref = _git(path, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if ref:  # refs/remotes/origin/<name>
        return ref.rsplit("/", 1)[-1]
    for cand in ("main", "master"):
        if _git(path, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{cand}") is not None:
            return cand
    up = _git(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if up:  # e.g. origin/feat/x -> strip the leading remote segment
        return up.split("/", 1)[1] if "/" in up else up
    default = _git(path, "config", "--get", "init.defaultBranch")
    if default:
        return default
    return None


def _opted_out(path):
    if os.environ.get("CT_NO_AUTO_FF", "").strip() == "1":
        return True
    conf = os.path.join(path, ".claude", "worktrees.conf")
    try:  # strict utf-8 decode; missing/unreadable/undecodable conf -> not opted out (parity w/ .cjs)
        with open(conf, "rb") as f:
            text = f.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    for line in text.split("\n"):
        if line.strip().replace(" ", "") == "CT_NO_AUTO_FF=1":
            return True
    return False


def _say(reason: str) -> str:
    """Write a breadcrumb to stderr (as before) AND return it, so a caller that drops stderr on
    exit-0 (session_autoff, merge_autoff) can still surface it on stdout (#924 silent-failure)."""
    sys.stderr.write(reason + "\n")
    return reason


def ff_checkout_if_safe(cwd) -> tuple:
    """Return (verdict, reason): verdict is "noop" | "ff" | "warn", never raising (fail-open).
    "noop" = nothing to do or not applicable (no repo, opted out, already up to date, or an
    unexpected error caught at the top); "warn" = behind but a gate declined (dirty / other-branch /
    diverged / a peer session on the primary / a failed ff); "ff" = a fast-forward was performed.
    `reason` is the one-line `fleet-freshness:` breadcrumb — NON-EMPTY for "warn" and for every
    DECLINED "noop" (so a silent miss can't read as "up to date" upstream), and "" for a genuine
    silent case (non-repo, opted out, up to date, successful ff — which still logs to stderr). The
    reason is also written to stderr exactly as before (byte-parity preserved)."""
    try:
        main = _main_worktree(cwd)
        if not main:
            # No main worktree. A genuine non-repo is a benign, silent noop; but if a `.git` exists at
            # cwd or an ancestor, the git-common-dir lookup FAILED (safe.directory refusal, broken
            # linked-worktree pointer, git missing/timeout, corrupt .git) — auto-ff turning off
            # silently there IS the #924 symptom, so leave a breadcrumb (#924 MEDIUM).
            if _has_dotgit_ancestor(cwd):
                return "noop", _say(
                    f"fleet-freshness: {cwd} is inside a git repo but `git rev-parse --git-common-dir` "
                    f"failed (safe.directory / broken worktree / git missing?) — not auto-ff'ing")
            return "noop", ""
        if _opted_out(main):  # deliberately frozen -> do nothing: no fetch, no nag (#801 T1)
            return "noop", ""
        _git(main, "fetch", "origin")  # fail-open inside _git
        trunk = _trunk(main)
        if not trunk:
            return "noop", _say(
                f"fleet-freshness: {main} — could not resolve the default branch — not auto-ff'ing")
        head = _git(main, "rev-parse", "HEAD")
        remote = _git(main, "rev-parse", f"origin/{trunk}")
        if not head or not remote:
            return "noop", _say(
                f"fleet-freshness: {main} — could not read HEAD or origin/{trunk} (rev-parse failed) — not auto-ff'ing")
        if head == remote:
            return "noop", ""  # genuinely up to date — silent
        cur = _git(main, "rev-parse", "--abbrev-ref", "HEAD")
        dirty = _git(main, "status", "--porcelain") or ""
        ancestor = subprocess.run(
            ["git", "-C", main, "merge-base", "--is-ancestor", "HEAD", f"origin/{trunk}"],
            capture_output=True, check=False).returncode == 0
        if cur != trunk or dirty or not ancestor:  # opt-out handled early (#801 T1); _git already strips (#805)
            return "warn", _say(
                f"fleet-freshness: {main} is behind origin/{trunk} but not auto-ff-able "
                f"(dirty/other-branch/diverged) — run: git -C {main} merge --ff-only "
                f"origin/{trunk}")
        # #924 — never auto-ff a checkout another live session may be using: a mutating FF on a
        # shared primary could yank the tree out from under a concurrent session. Reuses the same
        # heartbeat-lock signal session_start maintains.
        if _other_session_active(main):
            return "warn", _say(
                f"fleet-freshness: {main} is behind origin/{trunk} but another session is active "
                f"— not auto-ff'ing; run: git -C {main} merge --ff-only origin/{trunk}")
        # sanctioned safe ff on a possibly-shared checkout — scope the flag to THIS subprocess only
        # (T2/T3 call this in-process; don't leak it into the ambient hook env).
        if _git(main, "merge", "--ff-only", f"origin/{trunk}",
                env={**os.environ, "CT_ALLOW_SHARED": "1"}) is None:
            return "warn", _say(f"fleet-freshness: ff of {main} failed — run it by hand.")
        sys.stderr.write(f"fleet-freshness: ff'd {main} {head[:9]}->{remote[:9]} to match origin/{trunk}\n")
        return "ff", ""  # successful ff is informative on stderr but not a decline — silent on stdout
    except Exception as e:  # noqa: BLE001 — never let GC/ff break a hook
        return "noop", _say(
            f"fleet-freshness: ff aborted by an unexpected error ({e!r}) — not auto-ff'ing")


if __name__ == "__main__":  # CLI shim for tests — print ONLY the verdict (pr-merge-recover parses it)
    print(ff_checkout_if_safe(sys.argv[1] if len(sys.argv) > 1 else ".")[0])
