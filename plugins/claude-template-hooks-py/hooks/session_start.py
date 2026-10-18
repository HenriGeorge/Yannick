#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""SessionStart hook — load project status into context, incl. GATE-0 behind-count (H4) + HANDOFF.

SessionStart is INJECT-ONLY (researcher §4) — it can never block, so every code path here must
exit 0 and never raise. Best-effort `git fetch` (short timeout, fails SILENTLY offline), then
compute the local branch's behind-count (and, on the default branch, ahead-count — #457) vs the
default remote branch and inject it as an additionalContext line. Also surfaces the PRIMARY worktree's HANDOFF.md (session continuity) so a
fresh session reads it even though HANDOFF.md is gitignored and lives only in the main
checkout. Gracefully skips (no crash, no exception) when: not a git repo, detached HEAD / no branch,
no `origin` remote configured, no HANDOFF.md, or any git/read call fails.

Authored canonically here in the plugin (no `.tmpl` / `{{PROJECT}}` sed step). setup.sh copies this
file verbatim into a scaffolded project; the project name is derived at runtime from
`os.path.basename(os.getcwd())`, so the same source works for every project without substitution.
"""

import glob
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime

from _lib.session import is_child_session


# context-reinjection — single-sourced concise reminder text (must stay byte-identical to the
# CONCISE_REMINDER constant in hooks/node/session_start.cjs). Pointer-based, not a data dump (G2):
# the specifics live in the files it points to, which are always current. Bounded to ~15 lines (G1).
CONCISE_REMINDER = """⚠ Context was just compacted/resumed — your memory of this session may be stale. Trust the
durable records, not recall.

The two laws: Design → Code → Prove.
  GATE-1 — design before code (no implementation without an approved design).
  GATE-2 — evidence before "done" (fresh output THIS turn, never "should pass").

Re-read before acting: HANDOFF.md, crew/*.md (if you're in a crew), and the active task's
docs/superpowers/specs/ + docs/superpowers/plans/ files.

Verify against the durable records + origin/main before acting — don't assume."""


def _read_stdin_fields():
    """Best-effort read of the SessionStart hook's `source` + `session_id` fields from stdin JSON.

    stdin can only be read once, so this is the single read point for both — returns
    (source, session_id), each None if stdin is empty/unreadable/malformed or the field is absent
    (never raises). The caller treats a None source as the safe fallback (the FULL
    [Session Context] dump, not the concise reminder — G3/GP1, flipped post-review per
    crew/auditor-context-reinjection.md Finding 1).
    """
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            return None, None
        data = json.loads(raw)
        source = data.get("source")
        session_id = data.get("session_id")
        return (
            source if isinstance(source, str) else None,
            session_id if isinstance(session_id, str) else None,
        )
    except Exception:
        return None, None


def _run(args, cwd, timeout=5):
    """subprocess.run wrapper that never raises — returns None on any failure."""
    try:
        return subprocess.run(args, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    except Exception:
        return None


# (name, bin/ script, description) — `pluginver` (#963) only exists in the template repo itself.
_MERGE_DRIVERS = (
    ("docstamp", "git-merge-docstamp.sh", "Keep the newer Last-updated: stamp"),
    ("pluginver", "git-merge-plugin-version.sh", "Plugin version max+1 / fingerprint regen"),
)


def _register_merge_driver(project_dir):
    """Idempotently register the `docstamp` + `pluginver` git merge drivers in THIS clone's config.

    A driver named in .gitattributes (`*.md merge=docstamp`) is inert until the clone's git config
    points the name at a command — and that config can't be committed, so it must be set per-clone.
    This is the only per-session seam that reaches every existing clone (and every fleet repo, via
    the shipped hook). Best-effort + never raises: SessionStart is inject-only, never blocking, and
    an unregistered driver simply falls back to git's default text merge. Silent unless a
    `git config` write fails (then one stderr breadcrumb per driver).

    The config is SHARED by every worktree, so the path is built from the MAIN checkout (parent of
    the common git dir), never from a linked worktree that may later be removed — and a registered
    path whose script no longer exists is re-registered rather than trusted."""
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], project_dir, timeout=3)
    if not inside or inside.stdout.strip() != "true":
        return
    common = _run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], project_dir, timeout=3)
    root = project_dir
    if common is not None and common.returncode == 0 and common.stdout.strip():
        root = os.path.dirname(common.stdout.strip().rstrip("/"))
    for name, script, label in _MERGE_DRIVERS:
        try:  # per driver: one driver's failure never skips the other
            existing = _run(["git", "config", "--get", f"merge.{name}.driver"], project_dir, timeout=3)
            current = existing.stdout.strip() if existing is not None else ""
            if current:
                try:
                    registered = shlex.split(current)[0]
                except (ValueError, IndexError):
                    registered = ""
                if os.path.isfile(registered):
                    continue  # already registered to a live script — idempotent no-op
            driver = os.path.abspath(os.path.join(root, "bin", script))
            if not os.path.isfile(driver):
                continue  # driver script not present in this repo — nothing to wire
            # git runs the driver via `sh -c`: quote the path so spaces/metachars can't split or inject
            ok = all(
                r is not None and r.returncode == 0
                for r in (
                    _run(["git", "config", f"merge.{name}.name", label], project_dir, timeout=3),
                    _run(["git", "config", f"merge.{name}.driver", f"{shlex.quote(driver)} %O %A %B %L %P"],
                         project_dir, timeout=3),
                )
            )
            if not ok:
                print(f"session_start: could not register the {name} merge driver (git config failed)",
                      file=sys.stderr)
        except Exception as exc:
            print(f"session_start: {name} merge-driver registration error: {exc}", file=sys.stderr)


def _default_branch(project_dir):
    """Best-effort remote default branch name (e.g. 'main'), or None if it can't be determined."""
    ref = _run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], project_dir)
    if ref is not None and ref.returncode == 0 and ref.stdout.strip():
        return ref.stdout.strip().rsplit("/", 1)[-1]
    for candidate in ("main", "master"):
        check = _run(["git", "rev-parse", "--verify", "--quiet", f"origin/{candidate}"], project_dir)
        if check is not None and check.returncode == 0:
            return candidate
    return None


def _gate0_line(project_dir):
    """Returns the GATE-0 additionalContext line(s), or None to skip (never raises).

    One fetch, then: behind/ahead count of HEAD vs origin/<default> (H4, #457) and — folded in from
    the former #117 check — a stale LOCAL default-branch ref (common with worktrees: `git fetch`
    updates origin/main but not local main, so `git diff main` compares against merged-away state).
    """
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], project_dir, timeout=3)
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None  # not a git repo — H4.5

    remote_r = _run(["git", "remote", "get-url", "origin"], project_dir, timeout=3)
    if remote_r is None or remote_r.returncode != 0 or not remote_r.stdout.strip():
        return "GATE-0: no origin remote configured — skipping behind-count."  # H4.3

    fetch_r = _run(["git", "fetch", "--quiet", "origin"], project_dir, timeout=8)
    fetch_ok = fetch_r is not None and fetch_r.returncode == 0  # H4.4 fail-open on offline/timeout

    default_branch = _default_branch(project_dir)
    if not default_branch:
        return "GATE-0: no origin default branch found — skipping behind-count."

    ref = f"origin/{default_branch}"
    exists = _run(["git", "rev-parse", "--verify", "--quiet", ref], project_dir, timeout=3)
    if exists is None or exists.returncode != 0:
        note = " (git fetch failed — offline?)" if not fetch_ok else ""
        return f"GATE-0: no {ref} ref available{note} — skipping behind-count."
    rsha = exists.stdout.strip()
    suffix = " (git fetch failed — count may be stale)" if not fetch_ok else ""

    lines = []
    branch_r = _run(["git", "branch", "--show-current"], project_dir, timeout=3)
    branch = branch_r.stdout.strip() if branch_r is not None else ""
    if not branch:
        lines.append("GATE-0: detached HEAD or no current branch — skipping behind-count.")  # H4.3
    else:
        lines.extend(_behind_ahead_lines(project_dir, branch, default_branch, ref, suffix))

    # #117 — stale LOCAL default-branch ref vs the origin ref just fetched. Independent of the
    # branch/count above, so a detached HEAD or a failed rev-list never hides it.
    local = _run(["git", "rev-parse", "--verify", "--quiet", default_branch], project_dir, timeout=3)
    lsha = local.stdout.strip() if local is not None and local.returncode == 0 else ""
    if lsha and rsha and lsha != rsha:
        lines.append(
            f"⚠ GATE-0: your LOCAL '{default_branch}' ref ({lsha[:7]}) differs from "
            f"origin/{default_branch} ({rsha[:7]}) — it's stale. Run `git fetch` and rebase it, and "
            f"always diff against `origin/{default_branch}`, never bare local `{default_branch}`."
        )
    return "\n".join(lines) if lines else None


def _behind_ahead_lines(project_dir, branch, default_branch, ref, suffix):
    """H4/#457 behind + ahead lines for HEAD vs origin/<default>; [] when the count can't be read."""
    # --left-right gives "ahead<TAB>behind" in one call. behind (right) == HEAD..ref as before;
    # ahead (left) surfaces a polluted-ahead local main (#457) — behind=0 alone reads "up to date".
    count_r = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{ref}"], project_dir, timeout=3
    )
    if count_r is None or count_r.returncode != 0:
        return []  # can't compute — skip silently rather than guess
    try:
        ahead, n = (int(x) for x in count_r.stdout.split())
    except ValueError:
        return []
    lines = []
    if n > 0:
        lines.append(
            f"⚠ GATE-0: you are {n} commit(s) behind {default_branch}{suffix} — rebase before "
            "building (rules/workflow.md's GATE 0)."
        )
    # #457 — only when ON the default branch: a feature branch is naturally ahead (your own work).
    if branch == default_branch and ahead > 0:
        lines.append(
            f"⚠ GATE-0: your LOCAL '{default_branch}' is {ahead} commit(s) AHEAD of {ref}{suffix} — "
            "a shared checkout or concurrent session may have committed here; verify before "
            "building (rules/workflow.md's GATE 0)."
        )
    if not lines:
        lines.append(f"✓ GATE-0: up to date with {default_branch}{suffix}.")
    return lines


# H12 — CLAUDE.md always-core rule imports. `[ \t]*$` not `\s*$`: `\s` matches newlines, which
# would let one import line swallow the next.
_RULES_IMPORT_RE = re.compile(r"^@(\.claude/rules/[A-Za-z0-9._-]+\.md)[ \t]*$", re.M)


def _rules_load_line(project_dir):
    """H12 — warn when a rule CLAUDE.md imports will not actually load.

    Two failure modes, same consequence (the rule is silently absent from context) but different
    fixes: MISSING (no such file) and IGNORED (present here, but gitignored — so a fresh clone, CI
    checkout, or cloud sandbox gets nothing; the #194/#198 class). Inject-only, never raises;
    returns None to skip (no CLAUDE.md, no imports, or everything resolves). Absence of evidence is
    never reported as a problem: if git is unavailable, nothing is flagged as ignored.
    """
    claude_md = os.path.join(project_dir, "CLAUDE.md")
    if not os.path.isfile(claude_md):
        return None
    try:
        with open(claude_md, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except Exception:
        return None
    targets = sorted(set(_RULES_IMPORT_RE.findall(text)))
    if not targets:
        return None
    missing = []
    ignored = []
    for rel in targets:
        name = os.path.basename(rel)
        if not os.path.isfile(os.path.join(project_dir, rel)):
            missing.append(name)
            continue
        chk = _run(["git", "check-ignore", "-q", rel], project_dir, timeout=3)
        if chk is not None and chk.returncode == 0:
            ignored.append(name)
    if not missing and not ignored:
        return None
    parts = []
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if ignored:
        parts.append("gitignored (absent in a fresh clone/sandbox): " + ", ".join(ignored))
    return (
        f"⚠ GATE-0: {len(missing) + len(ignored)} imported rule(s) will not load — "
        + "; ".join(parts)
        + " — see the claude-template-core plugin (docs/workflow/ENFORCEMENT.md) H12"
    )


_PRIME_CORE_REL = os.path.join("commands", "prime-core.md")


def _prime_core_body(project_dir):
    """The /prime-core command text to inject when the session is unprimed, frontmatter stripped;
    None when no copy is reachable. Lookup order: the checkout's own .claude/commands (fleet vendored
    copy / cloud-materialized), the source repo's plugin tree, then the plugin cache. The cache is laid
    out <cache>/<marketplace>/<plugin>/<version>/ and CLAUDE_PLUGIN_ROOT is THIS plugin's version dir,
    so the core plugin's copy is two levels up, under its own newest version dir."""
    cands = [os.path.join(project_dir, ".claude", _PRIME_CORE_REL),
             os.path.join(project_dir, "plugins", "claude-template-core", _PRIME_CORE_REL)]
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if root:
        marketplace = os.path.dirname(os.path.dirname(root.rstrip(os.sep)))
        versions = glob.glob(os.path.join(marketplace, "claude-template-core", "*", _PRIME_CORE_REL))

        def _ver_key(path):
            seg = os.path.basename(os.path.dirname(os.path.dirname(path)))
            return tuple(int(x) if x.isdigit() else -1 for x in seg.split("."))

        cands.extend(sorted(versions, key=_ver_key, reverse=True))
    for p in cands:
        try:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                text = text[end + 4:]
        text = text.strip()
        if text:
            return text
    return None


def _prime_gate_line(project_dir, session_id=None):
    """Loud first-action instruction when session_prime_gate WILL block the first mutation.

    Managed repo + on the shared primary checkout OR not yet primed → the gate blocks edits/commits,
    so tell the agent up front. Inject-only; the PreToolUse `session_prime_gate` does the enforcing.
    Silent when isolated + primed-for-this-session, on a non-managed repo, or when the gate is
    disabled/bypassed. A marker left by a DIFFERENT session (stale — the common case: a new session
    opened in an old worktree) is removed here (coordinator only — a child session never touches the
    parent's marker) so the next `/prime-core` re-primes cleanly, and the cue says so.
    """
    if os.environ.get("PRIME_GATE") == "0":
        return None
    if is_child_session():
        return None
    if not (os.path.isfile(os.path.join(project_dir, ".claude", "worktrees.conf"))
            or os.path.isfile(os.path.join(project_dir, "project-context.md"))):
        return None
    gdp = _run(["git", "rev-parse", "--absolute-git-dir"], project_dir)
    cdp = _run(["git", "rev-parse", "--git-common-dir"], project_dir)
    gd = gdp.stdout.strip() if gdp else ""
    cd = cdp.stdout.strip() if cdp else ""
    if cd and not os.path.isabs(cd):
        cd = os.path.abspath(os.path.join(project_dir, cd))
    on_primary = bool(gd) and os.path.realpath(gd) == os.path.realpath(cd)
    marker_path = os.path.join(project_dir, ".claude", "state", "primed")
    try:
        with open(marker_path, encoding="utf-8") as fh:
            content = fh.read().strip()
    except OSError:
        content = ""
    primed = bool(content) and content == (session_id or content)
    stale = bool(content) and session_id and content != session_id
    prefix = ""
    if stale:
        try:
            os.remove(marker_path)
            prefix = "(stale prime marker from a previous session removed) "
        except OSError:
            # Never claim a removal that did not happen; the gate still denies on the mismatch.
            prefix = "(stale prime marker from a previous session present; could not remove it) "
    if not on_primary and primed:
        return None
    if not primed:
        first = "`/prime-core` (it fast-forwards local main from origin/main and enters a worktree off it)"
    else:
        first = "`EnterWorktree` (fresh off origin/main)"
    line = (prefix + "⛔ First action: " + first
            + " — edits/commits are BLOCKED by session_prime_gate until done"
            + " (bypass: WORKFLOW:no-worktree / WORKFLOW:no-prime, or PRIME_GATE=0).")
    if not primed:
        body = _prime_core_body(project_dir)
        if body:
            line += ("\n\n⛔ /prime-core — execute these steps now, in order, then write the marker "
                     "(a hook cannot run the command for you):\n" + body)
    return line


def _primary_worktree(project_dir):
    """Absolute path of the PRIMARY worktree (first entry of `git worktree list`), or None.

    Works whether the hook runs in the main checkout or a sibling worktree — the first
    porcelain entry is always the primary, which is where gitignored files like HANDOFF.md live.
    """
    r = _run(["git", "worktree", "list", "--porcelain"], project_dir, timeout=3)
    if r is None or r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            return line[len("worktree "):].strip()
    return None


def _mainref(project_dir):
    """`origin/main` when it exists (fresh from the startup fetch), else local `main`."""
    r = _run(["git", "rev-parse", "--verify", "--quiet", "origin/main"], project_dir, timeout=5)
    return "origin/main" if (r is not None and r.returncode == 0 and r.stdout.strip()) else "main"


def _wt_merged(project_dir, tip, mainref):
    """True if the branch's work is already in main — squash-safe: ancestry OR content-identical trees."""
    a = _run(["git", "merge-base", "--is-ancestor", tip, mainref], project_dir, timeout=5)
    if a is not None and a.returncode == 0:
        return True
    d = _run(["git", "diff", "--quiet", mainref, tip], project_dir, timeout=5)
    return d is not None and d.returncode == 0


def _cleanup_dangling_worktrees(project_dir):
    """Worktree hygiene at the one safe point (no agent occupies a stale tree): (1) `git worktree
    prune` drops entries whose dir is already gone; (2) reap MERGED clean `.claude/worktrees/*`
    siblings via plain `git worktree remove` (never --force — a dirty tree is refused, so in-progress
    work is never lost; the branch ref survives). Never the current tree, the primary, or a worktree
    a live peer session occupies (#1235). Best-effort; never raises; returns a status line or None.
    """
    _run(["git", "worktree", "prune"], project_dir, timeout=5)

    r = _run(["git", "worktree", "list", "--porcelain"], project_dir, timeout=5)
    if r is None or r.returncode != 0:
        return None

    own = None
    tl = _run(["git", "rev-parse", "--show-toplevel"], project_dir, timeout=5)
    if tl is not None and tl.returncode == 0 and tl.stdout.strip():
        own = os.path.realpath(tl.stdout.strip())
    primary = _primary_worktree(project_dir)
    primary = os.path.realpath(primary) if primary else None
    marker = os.sep + os.path.join(".claude", "worktrees") + os.sep

    mainref = _mainref(project_dir)
    peer_cwds = _live_peer_cwds(project_dir)
    reaped = []
    for block in r.stdout.split("\n\n"):
        path = branch = head = None
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree "):].strip()
            elif line.startswith("branch "):
                branch = line[len("branch "):].strip()
            elif line.startswith("HEAD "):
                head = line[len("HEAD "):].strip()
        if not path:
            continue
        rp = os.path.realpath(path)
        if rp == own or rp == primary or marker not in (rp + os.sep):
            continue
        if rp in peer_cwds:
            continue
        tip = branch or head
        if not tip or not _wt_merged(project_dir, tip, mainref):
            continue
        rr = _run(["git", "worktree", "remove", path], project_dir, timeout=10)  # NO --force
        if rr is not None and rr.returncode == 0:
            reaped.append(os.path.basename(rp))

    if not reaped:
        return None
    noun = "tree" if len(reaped) == 1 else "trees"
    return f"worktree hygiene: reaped {len(reaped)} merged worktree {noun} ({', '.join(reaped)})"


def _handoff_context(project_dir):
    """Return the primary worktree's HANDOFF.md (+ TASKS.md) as a labelled block, or None.

    Best-effort and never raises: skips silently on any failure or when the file is absent/empty.
    Caps very large files (head + a pointer) so a giant handoff can't flood the context window.
    """
    primary = _primary_worktree(project_dir)
    if not primary:
        return None

    MAX_LINES = 200
    blocks = []
    for fname in ("HANDOFF.md", "TASKS.md"):
        path = os.path.join(primary, fname)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except Exception:
            continue
        if not text.strip():
            continue
        lines = text.splitlines()
        if len(lines) > MAX_LINES:
            text = "\n".join(lines[:MAX_LINES]) + f"\n… [truncated — full file at {path}]"
        blocks.append(f"[{fname} — session continuity, from {path}]\n{text}")

    return "\n\n".join(blocks) if blocks else None


# §81 — concurrent-session check. On startup the hook drops a heartbeat lock keyed by the claude
# session PID (os.getppid()) and warns when ANOTHER live session already holds a lock for this repo
# — the shared-checkout collision the workflow's "/rc" concept meant to catch. Inject-only: never
# blocks, fails open on any error. Lock dir is per-repo (git common dir) so it detects sessions
# across worktrees too; CT_SESSION_DIR redirects it (test seam). Pruning is PID-liveness only — a
# dead session's lock is removed on the next start, a live one stays. (Accepted limitation: PID
# reuse could keep a dead session's lock looking live until that PID is recycled — an advisory
# false-positive, never a block.) The same lock dir is read by guards/shared_checkout and
# _ff_checkout.
_LOCK_STALE_SECS = 30  # prune an UNREADABLE lock only once older than this (past the write window)


def _session_lock_dir(project_dir):
    override = os.environ.get("CT_SESSION_DIR")
    if override:
        return override
    common = ""
    try:
        common = (_run(["git", "rev-parse", "--git-common-dir"], project_dir).stdout or "").strip()
    except Exception:
        common = ""
    if common and not os.path.isabs(common):
        common = os.path.join(os.path.abspath(project_dir or "."), common)
    # realpath both sides so a symlinked path (e.g. /tmp -> /private/tmp on macOS) keys to the same
    # dir the ff primitive (_ff_checkout._lock_dir) computes — shared normalization (#924 MEDIUM).
    base = os.path.realpath(common) if common else os.path.realpath(project_dir or ".")
    key = base.replace(os.sep, "-").strip("-") or "root"
    return os.path.join(os.path.expanduser("~/.local/share/claude-template/sessions"), key)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except Exception:
        return False


def _live_peer_cwds(project_dir):
    """Realpath'd cwds of OTHER live sessions holding a §81 lock for this repo — used to protect a
    peer's worktree from the merged-worktree reap (#1235). Best-effort; never raises (inject-only)."""
    out = set()
    try:
        d = _session_lock_dir(project_dir)
        me = os.getppid()
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, name)) as fh:
                    rec = json.load(fh)
                pid = int(rec.get("pid"))
            except Exception:
                continue
            if pid == me or not _pid_alive(pid):
                continue
            cwd = rec.get("cwd")
            if cwd:
                out.add(os.path.realpath(cwd))
    except Exception:
        pass
    return out


def _concurrent_session_line(project_dir):
    """One-line warning if another LIVE session holds a lock for this repo, else None. Prunes
    dead/unreadable locks as a side effect. Never raises (inject-only)."""
    d = _session_lock_dir(project_dir)
    try:
        os.makedirs(d, exist_ok=True)
        names = [n for n in os.listdir(d) if n.endswith(".json")]
    except Exception:
        return None
    me = os.getppid()
    now = datetime.now().timestamp()
    others = []
    for name in names:
        p = os.path.join(d, name)
        try:
            with open(p) as fh:
                rec = json.load(fh)
            pid = int(rec.get("pid"))
        except Exception:
            # An unreadable file is NOT evidence the owner is dead — it may be a lock being written
            # RIGHT NOW by a starting session (writes are temp+rename atomic, but be defensive). Only
            # prune once it is clearly past the write window, never mid-write — else a live session's
            # lock gets destroyed and it goes invisible forever (silent-failure-hunter #1).
            try:
                if (now - os.path.getmtime(p)) > _LOCK_STALE_SECS:
                    os.remove(p)
            except Exception:
                pass
            continue
        if not _pid_alive(pid):
            try:
                os.remove(p)
            except Exception:
                pass
            continue
        if pid != me:
            others.append(rec)
    if not others:
        return None
    count = len(others)
    where = ", ".join(sorted({str(r.get("cwd", "?")) for r in others})[:3])
    return (
        "\n⚠ CONCURRENT SESSION: %d other Claude session%s active on this repo (%s). Another session "
        "may share this checkout — avoid a shared-checkout collision; work in your own worktree."
        % (count, "" if count == 1 else "s", where)
    )


def _write_session_lock(project_dir):
    """Best-effort heartbeat lock keyed by this session's PID. Never raises (inject-only)."""
    try:
        d = _session_lock_dir(project_dir)
        os.makedirs(d, exist_ok=True)
        me = os.getppid()
        rec = {
            "pid": me,
            "cwd": os.path.abspath(project_dir or "."),
            "started": int(datetime.now().timestamp()),
        }
        final = os.path.join(d, "%d.json" % me)
        tmp = final + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(rec, fh)
        os.replace(tmp, final)  # atomic on POSIX — a peer reader never sees a partial file
    except Exception:
        pass


_CRUMB_MAX = 1500  # chars — a crumb is a short re-grounding note, not a transcript


def _crumb_line(project_dir):
    """Prev-session crumb (READ-ONLY; written by session_crumb.py on PreCompact/SessionEnd;
    SESSION_CRUMB_PATH override, capped), or None."""
    crumb_path = os.environ.get("SESSION_CRUMB_PATH") or os.path.join(
        project_dir, ".claude", "state", "session_resume", "crumb.md"
    )
    try:
        with open(crumb_path, encoding="utf-8", errors="replace") as fh:
            crumb = fh.read().strip()
    except OSError:
        return None
    if not crumb:
        return None
    if len(crumb) > _CRUMB_MAX:
        crumb = crumb[:_CRUMB_MAX].rstrip() + "…"
    return "Last session crumb (re-grounding):\n" + crumb


def main():
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    # Register the merge drivers every session (idempotent, cheap, no output) — BEFORE the
    # concise/full branch split so it also runs on compact/resume.
    _register_merge_driver(project_dir)

    # context-reinjection — source-aware branch. ONLY an explicit source of "compact"/"resume"
    # takes the concise-reminder path. Every other case — startup, clear, fork, any other explicit
    # value, AND an unreadable/absent source — falls back to the full [Session Context] dump
    # (G3/GP1): silently dropping the GATE-0 warnings and HANDOFF surfacing on an unrecognized
    # source is a worse failure mode than being verbose on an actual compact/resume.
    source, session_id = _read_stdin_fields()
    concise = source in ("compact", "resume")

    if concise:
        lines = [CONCISE_REMINDER]
        try:
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, cwd=project_dir,
            ).stdout.strip()
            if branch:
                lines.append(f"\nCurrent branch: {branch}")
        except Exception:
            pass
        if source == "resume":  # a crumb re-grounds a resume; mid-session compact stays minimal
            try:
                crumb = _crumb_line(project_dir)
                if crumb:
                    lines.append(crumb)
            except Exception:
                pass
        print("\n".join(lines))
        return

    status_lines = ["[" + os.path.basename(os.getcwd()) + " Session Context]"]

    # Git branch
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=project_dir,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=project_dir,
        ).stdout.strip()
        status_lines.append(f"Branch: {branch}" + (" (dirty)" if dirty else " (clean)"))
    except Exception:
        pass

    # Every producer below is isolated: a bug in one must never crash the inject-only hook or
    # drop the others' lines.
    for fn in (_gate0_line, _rules_load_line,
               lambda pd: _prime_gate_line(pd, session_id), _cleanup_dangling_worktrees):
        try:
            line = fn(project_dir)
            if line:
                status_lines.append(line)
        except Exception as exc:
            print(f"session_start: {fn.__name__} failed (fail-open): {exc}", file=sys.stderr)

    handoff = None
    try:
        handoff = _handoff_context(project_dir)
    except Exception:
        handoff = None

    # §81 — detect BEFORE writing our own lock so we never flag ourselves.
    try:
        cs = _concurrent_session_line(project_dir)
        if cs:
            status_lines.append(cs)
    except Exception:
        pass
    try:
        _write_session_lock(project_dir)
    except Exception:
        pass

    try:
        crumb = _crumb_line(project_dir)
        if crumb:
            status_lines.append(crumb)
    except Exception:
        pass

    print("\n".join(status_lines))
    if handoff:
        print("\n" + handoff)


if __name__ == "__main__":
    main()
