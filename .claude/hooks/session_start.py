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

import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime


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


def _read_source():
    """Best-effort read of the SessionStart hook's `source` field from stdin JSON.

    Returns the source string, or None if stdin is empty/unreadable/malformed (never raises) — the
    caller treats None as the safe fallback (the FULL [Session Context] dump, not the concise
    reminder — G3/GP1, flipped post-review per crew/auditor-context-reinjection.md Finding 1).
    """
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            return None
        data = json.loads(raw)
        source = data.get("source")
        return source if isinstance(source, str) else None
    except Exception:
        return None


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
    """Returns a GATE-0 additionalContext line, or None to skip (never raises)."""
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], project_dir, timeout=3)
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return None  # not a git repo — H4.5

    branch_r = _run(["git", "branch", "--show-current"], project_dir, timeout=3)
    branch = branch_r.stdout.strip() if branch_r is not None else ""
    if not branch:
        return "GATE-0: detached HEAD or no current branch — skipping behind-count."  # H4.3

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

    # --left-right gives "ahead<TAB>behind" in one call. behind (right) == HEAD..ref as before;
    # ahead (left) surfaces a polluted-ahead local main (#457) — behind=0 alone reads "up to date".
    count_r = _run(
        ["git", "rev-list", "--left-right", "--count", f"HEAD...{ref}"], project_dir, timeout=3
    )
    if count_r is None or count_r.returncode != 0:
        return None  # can't compute — skip silently rather than guess

    try:
        ahead, n = (int(x) for x in count_r.stdout.split())
    except ValueError:
        return None

    suffix = " (git fetch failed — count may be stale)" if not fetch_ok else ""
    # #457 — only when ON the default branch: a feature branch is naturally ahead (your own work).
    ahead_warn = None
    if branch == default_branch and ahead > 0:
        ahead_warn = (
            f"⚠ GATE-0: your LOCAL '{default_branch}' is {ahead} commit(s) AHEAD of {ref}{suffix} — "
            "a shared checkout or concurrent session may have committed here; verify before "
            "building (rules/workflow.md's GATE 0)."
        )
    if n > 0:
        behind_line = (
            f"⚠ GATE-0: you are {n} commit(s) behind {default_branch}{suffix} — rebase before "
            "building (rules/workflow.md's GATE 0)."
        )
        return behind_line + ("\n" + ahead_warn if ahead_warn else "")
    if ahead_warn:
        return ahead_warn
    return f"✓ GATE-0: up to date with {default_branch}{suffix}."


def _stale_local_main_line(project_dir):
    """#117 — warn when the LOCAL default-branch ref has drifted from origin/<branch>.

    A stale local `main` (common with worktrees: `git fetch` updates origin/main but not the local
    ref) makes `git diff main` compare against merged-away state — the exact misread this closes.
    Inject-only, never raises; returns None to skip (no default branch, either ref missing, refs
    equal, or any failure). Reuses the origin/<branch> that _gate0_line already fetched — no 2nd
    fetch here.
    """
    default_branch = _default_branch(project_dir)
    if not default_branch:
        return None
    local = _run(["git", "rev-parse", "--verify", "--quiet", default_branch], project_dir, timeout=3)
    remote = _run(
        ["git", "rev-parse", "--verify", "--quiet", f"origin/{default_branch}"], project_dir, timeout=3
    )
    if local is None or remote is None or local.returncode != 0 or remote.returncode != 0:
        return None
    lsha = local.stdout.strip()
    rsha = remote.stdout.strip()
    if not lsha or not rsha or lsha == rsha:
        return None
    return (
        f"⚠ GATE-0: your LOCAL '{default_branch}' ref ({lsha[:7]}) differs from "
        f"origin/{default_branch} ({rsha[:7]}) — it's stale. Run `git fetch` and rebase it, and "
        f"always diff against `origin/{default_branch}`, never bare local `{default_branch}`."
    )


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


# LSP preflight (#lsp-default-on) — an enabled `*-lsp` plugin ships a Claude-side client but NOT the
# language server itself; the server is a separate `npm i -g` binary. When it's absent from PATH the
# plugin silently degrades to the grep fallback, so warn at SessionStart with the exact install
# command. Map key = the plugin's short name (the part before `@`); value = its server binary /
# install line. Kept byte-identical to the same two maps in hooks/node/session_start.cjs.
_LSP_SERVER_BIN = {"typescript-lsp": "typescript-language-server", "pyright-lsp": "pyright"}
_LSP_INSTALL = {"typescript-lsp": "npm i -g typescript typescript-language-server",
                "pyright-lsp": "npm i -g pyright"}


def _lsp_preflight_line(project_dir):
    """WARN if an enabled *-lsp plugin has no server binary on PATH (never raises)."""
    try:
        import shutil
        sp = os.path.join(project_dir, ".claude", "settings.json")
        if not os.path.exists(sp):
            return None
        with open(sp, encoding="utf-8") as f:
            enabled = json.load(f).get("enabledPlugins", {})
        missing = []
        for key in enabled:
            name = key.split("@", 1)[0]
            binname = _LSP_SERVER_BIN.get(name)
            if binname and enabled[key] and shutil.which(binname) is None:
                missing.append("%s (%s)" % (name, _LSP_INSTALL[name]))
        if missing:
            return "⚠ LSP enabled but server missing — grep fallback in effect. Install: " + "; ".join(missing)
        return None
    except Exception:
        return None


def _prime_gate_line(project_dir):
    """Loud first-action instruction when session_prime_gate WILL block the first mutation.

    Managed repo + on the shared primary checkout OR not yet primed → the gate blocks edits/commits,
    so tell the agent up front. Inject-only; the PreToolUse `session_prime_gate` does the enforcing.
    Silent when isolated + primed, on a non-managed repo, or when the gate is disabled/bypassed.
    """
    if os.environ.get("PRIME_GATE") == "0":
        return None
    if not (os.path.isfile(os.path.join(project_dir, ".claude", "worktrees.conf"))
            or os.path.isfile(os.path.join(project_dir, "project-context.md"))):
        return None
    if os.path.isfile(os.path.join(project_dir, ".claude", "state", "prime-bypass")):
        return None
    gdp = _run(["git", "rev-parse", "--absolute-git-dir"], project_dir)
    cdp = _run(["git", "rev-parse", "--git-common-dir"], project_dir)
    gd = gdp.stdout.strip() if gdp else ""
    cd = cdp.stdout.strip() if cdp else ""
    if cd and not os.path.isabs(cd):
        cd = os.path.abspath(os.path.join(project_dir, cd))
    on_primary = bool(gd) and os.path.realpath(gd) == os.path.realpath(cd)
    primed = os.path.isfile(os.path.join(project_dir, ".claude", "state", "primed"))
    if not on_primary and primed:
        return None
    needs = []
    if on_primary:
        needs.append("`EnterWorktree` (fresh off origin/main)")
    if not primed:
        needs.append("`/prime-core`")
    return ("⛔ First action: " + " then ".join(needs)
            + " — edits/commits are BLOCKED by session_prime_gate until "
            + ("both" if len(needs) > 1 else "done")
            + " (bypass: WORKFLOW:no-worktree / WORKFLOW:no-prime, or PRIME_GATE=0).")


# S1 (plugin install hygiene spec, F1) — warn when this repo's installed claude-template-hooks-py
# (user scope) trails origin/main's marketplace.json version. claude_template ONLY (detected by a
# root .claude-plugin/marketplace.json naming "claude-template"); skipped entirely in the cloud
# (CLAUDE_CODE_REMOTE=true), where the cloud analogue is train-2 T3's vendor-tooling.sh --check.
# Any read error -> silent (advisory; plugin-doctor reports the details). No fetch here —
# session_start already fetched earlier in GATE-0 (_gate0_line).
def _is_claude_template_repo(project_dir):
    try:
        with open(os.path.join(project_dir, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            return json.load(f).get("name") == "claude-template"
    except Exception:
        return False


def _version_lt(a, b):
    """Dotted-int version compare, zero-padded so '1.0' == '1.0.0' (matches the node twin's
    pa[i]||0 padding); non-numeric parts fall back to a lexical compare (never raises)."""
    def parts(v):
        try:
            return [int(x) for x in v.split(".")]
        except ValueError:
            return None
    pa, pb = parts(a), parts(b)
    if pa is not None and pb is not None:
        n = max(len(pa), len(pb))
        pa += [0] * (n - len(pa))
        pb += [0] * (n - len(pb))
        return pa < pb
    return a < b


def _plugin_behind_line(project_dir):
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return None
    if not _is_claude_template_repo(project_dir):
        return None
    try:
        plugins_dir = os.environ.get("CT_PLUGINS_DIR") or os.path.join(
            os.path.expanduser("~"), ".claude", "plugins"
        )
        with open(os.path.join(plugins_dir, "installed_plugins.json"), encoding="utf-8") as f:
            installed = json.load(f)
        entries = installed["plugins"]["claude-template-hooks-py@claude-template"]
        have = next(e["version"] for e in entries if e.get("scope") == "user")
        r = _run(["git", "show", "origin/main:.claude-plugin/marketplace.json"], project_dir, timeout=5)
        if r is None or r.returncode != 0:
            return None
        want = json.loads(r.stdout).get("version")
        if not want or not _version_lt(have, want):
            return None
        return (
            f"plugins: hooks {have} < origin/main {want} -- ff the primary main, then: "
            "claude plugin update claude-template-hooks-py@claude-template --scope user (+ core); restart"
        )
    except Exception:
        return None


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


# Fixed Mon..Sun lookup keyed on datetime.weekday() (0=Monday) — locale-INDEPENDENT, matched to
# the Node side's forced `toLocaleDateString('en-US', {weekday: 'short'})`. strftime("%a") would
# silently emit the SYSTEM locale's abbreviation (e.g. "lun." under LC_TIME=fr_FR.UTF-8), so an
# English-keyed reminders.json would quietly never fire on a non-English-locale host — fail-open
# swallows the miss with no crash, just a missing reminder. This table sidesteps that entirely.
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _reminder_line(project_dir):
    """#7 — optional day-of-week reminder from `.claude/reminders.json` (PROJECT dir, opt-in).

    Maps a 3-letter weekday short-name (e.g. "Mon") to a message; if today's key is present,
    returns that message as a single line. Fail-open: absent, unreadable, or malformed
    reminders.json (not a JSON object, wrong value type, etc.) returns None — never raises, never
    changes SessionStart's exit code. `.claude/reminders.example.json` is a separate, INERT file —
    it is never read here.
    """
    try:
        path = os.path.join(project_dir, ".claude", "reminders.json")
        if not os.path.isfile(path):
            return None
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return None
        today = _WEEKDAYS[datetime.now().weekday()]
        message = data.get(today)
        return message if isinstance(message, str) and message else None
    except Exception:
        return None


# seam-contract (docs/superpowers/specs/2026-08-12-seam-contract-design.md): optional repo-local
# `.claude/session-start.json` lets a project add context notes WITHOUT forking this hook —
# {"extraNotes":[{"cmd":["argv","…"],"timeoutMs":20000}]}. Inject-only discipline: absent,
# malformed, wrong-typed, unspawnable, or timed-out seams are a SILENT no-op — a broken seam must
# never break a session. The cmd's EXIT CODE is not a gate: non-zero exit still relays captured
# stdout (amended 2026-08-12 after the ableton canary — check-index emits its signal lines WITH
# exit 1/2, and the fork relayed them). Argv arrays only (no shell), per-cmd timeout default 20s capped
# 30s, stdout capped ~2KB (truncate + ellipsis), cwd = project dir. Tests point at an alternate
# seam FILE via the CLAUDE_SEAM_SESSION_START env override.
SEAM_DEFAULT_TIMEOUT_MS = 20000
SEAM_MAX_TIMEOUT_MS = 30000
SEAM_MAX_STDOUT = 2048


def _seam_extra_note_lines(project_dir):
    """Trimmed stdout of each well-formed extraNotes cmd, as context lines. Never raises; every
    failure path (including a single bad entry among good ones) degrades to skipping that entry.
    Called ONLY from the full-dump branch — the concise compact/resume path never runs seams (P3).
    """
    lines = []
    try:
        seam_path = os.environ.get("CLAUDE_SEAM_SESSION_START") or os.path.join(
            project_dir or ".", ".claude", "session-start.json"
        )
        if not os.path.isfile(seam_path):
            return []
        with open(seam_path, encoding="utf-8") as fh:
            data = json.load(fh)
        notes = data.get("extraNotes") if isinstance(data, dict) else None
        if not isinstance(notes, list):
            return []
        for entry in notes:
            try:
                if not isinstance(entry, dict):
                    continue
                cmd = entry.get("cmd")
                if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
                    continue  # argv array of strings only — never a shell string
                timeout_ms = entry.get("timeoutMs", SEAM_DEFAULT_TIMEOUT_MS)
                if not isinstance(timeout_ms, (int, float)) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
                    timeout_ms = SEAM_DEFAULT_TIMEOUT_MS
                timeout_ms = min(timeout_ms, SEAM_MAX_TIMEOUT_MS)
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=project_dir or None,
                    timeout=timeout_ms / 1000.0, check=False,
                )
                # exit code is NOT a gate — relay captured stdout regardless (spawn-failure and
                # timeout raise and are swallowed below; a non-zero exit with output still speaks).
                out = (result.stdout or "").strip()
                if not out:
                    continue
                if len(out) > SEAM_MAX_STDOUT:
                    out = out[:SEAM_MAX_STDOUT] + "…"
                lines.append(out)
            except Exception:
                continue  # missing binary / timeout / any per-entry failure → skip this entry
    except Exception:
        return []
    return lines


# §81 — concurrent-session check. On startup the hook drops a heartbeat lock keyed by the claude
# session PID (os.getppid()) and warns when ANOTHER live session already holds a lock for this repo
# — the shared-checkout collision the workflow's "/rc" concept meant to catch (there is no /rc
# command; this is its deterministic replacement). Inject-only: never blocks, fails open on any
# error. Lock dir is per-repo (git common dir) so it detects sessions across worktrees too;
# CT_SESSION_DIR redirects it (test seam). Pruning is PID-liveness only — a dead session's lock is
# removed on the next start, a live one stays. (Accepted limitation: PID reuse could keep a dead
# session's lock looking live until that PID is recycled — an advisory false-positive, never a
# block. No heartbeat beyond start, so this stays a single-file, stop-hook-free mechanism.)
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


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Folded-in SessionStart reporters. These three were standalone inject-only SessionStart hooks
# (session_report @order 35, session_resume @order 40, mcp_health @order 30) that only ever PRINTED
# context — consolidated here so SessionStart is one hook, not four. Each producer is inject-only
# and wrapped in its own try/except by _reporter_lines below; a producer bug never crashes the hook.
# The session_resume CRUMB WRITER stays a separate PreCompact hook (session_crumb.py) — only its
# READ leg moved here. Output wording is byte-identical to the deleted hooks so downstream tooling
# reads the same lines.

def _fmt_tok(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n / 1000:.1f}k"


def _cost_line(project_dir):
    """💰 last/total token cost from .claude/telemetry/costs.jsonl (SR_COSTS override). None if empty."""
    path = os.environ.get("SR_COSTS") or os.path.join(
        project_dir, ".claude", "telemetry", "costs.jsonl"
    )
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:  # json.JSONDecodeError subclasses ValueError
                continue
    if not rows:
        return None
    tot_tok = sum(r.get("total_tokens", 0) or 0 for r in rows)
    tot_cost = sum(r.get("cost_usd", 0) or 0 for r in rows)
    last = rows[-1]
    lt = last.get("total_tokens", 0) or 0
    lc = last.get("cost_usd", 0) or 0
    return (
        f"\U0001f4b0 last session: {_fmt_tok(lt)} tok · ${lc:.2f}"
        f"   (total: {_fmt_tok(tot_tok)} · ${tot_cost:.2f})"
    )


def _plan_name(fn):
    stem = fn[:-3] if fn.endswith(".md") else fn
    # strip a leading YYYY-MM-DD- date prefix if present
    parts = stem.split("-", 3)
    if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
        return parts[3]
    return stem


def _plans_line(project_dir):
    """📋 plans in flight from docs/superpowers/plans/ (SR_PLANS_DIR override). None if none."""
    d = os.environ.get("SR_PLANS_DIR") or os.path.join(
        project_dir, "docs", "superpowers", "plans"
    )
    files = sorted(f for f in os.listdir(d) if f.endswith(".md"))
    if not files:
        return None
    names = ", ".join(_plan_name(f) for f in files[:3])
    return f"\U0001f4cb plans in flight: {len(files)} — {names}"


def _state_line(_project_dir):
    """🧹 per-session state-file count under ~/.claude/state (SR_STATE_DIR override). None if 0."""
    d = os.environ.get("SR_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "state")
    count = 0
    for _root, _dirs, files in os.walk(d):
        count += len(files)
    if count == 0:
        return None
    hint = "  (>30 → consider prune)" if count > 30 else ""
    return f"\U0001f9f9 state: {count} session files{hint}"


# session_resume — first lockfile that exists wins (most specific / least ambiguous first)
_LOCKFILES = [
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("package-lock.json", "npm"),
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("Cargo.lock", "cargo"),
    ("go.sum", "go"),
]
_CRUMB_MAX = 1500  # chars — a crumb is a short re-grounding note, not a transcript


def _detect_pm(root):
    for fname, pm in _LOCKFILES:
        if os.path.isfile(os.path.join(root, fname)):
            return pm, fname
    return None, None


def _resume_lines(project_dir):
    """Prev-session crumb (READ-ONLY; SESSION_CRUMB_PATH override, capped) + package-manager line."""
    lines = []
    crumb_path = os.environ.get("SESSION_CRUMB_PATH") or os.path.join(
        project_dir, ".claude", "state", "session_resume", "crumb.md"
    )
    crumb = ""
    try:
        with open(crumb_path, encoding="utf-8", errors="replace") as fh:
            crumb = fh.read().strip()
    except OSError:
        crumb = ""
    pm, lockfile = _detect_pm(project_dir)
    if crumb:
        if len(crumb) > _CRUMB_MAX:
            crumb = crumb[:_CRUMB_MAX].rstrip() + "…"
        lines.append("Last session crumb (re-grounding):\n" + crumb)
    if pm:
        lines.append(f"Package manager: {pm} ({lockfile})")
    return lines


# mcp_health — a line is "unhealthy" if it carries any of these markers (claude mcp list uses ✗ / "Failed")
_MCP_DEFAULT_CMD = "claude mcp list"
_MCP_DEFAULT_TIMEOUT = 5
_MCP_UNHEALTHY_MARKERS = ("✗", "failed", "disconnected", "error")


def _mcp_server_name(line):
    """Best-effort server name from a `name: transport - ✗ Failed…` line."""
    head = line.split(" - ", 1)[0]
    head = head.split(":", 1)[0]
    return head.strip() or line.strip()


def _mcp_health_line():
    """Warn on disconnected/failed MCP servers from `claude mcp list` (MCP_HEALTH_CMD override).

    Guarded short timeout (MCP_HEALTH_TIMEOUT, default 5s), fail-silent: a missing CLI or slow probe
    returns None. Fixed, operator-set command; shell=False.
    """
    cmd = shlex.split(os.environ.get("MCP_HEALTH_CMD") or _MCP_DEFAULT_CMD)
    if not cmd:
        return None
    try:
        timeout = float(os.environ.get("MCP_HEALTH_TIMEOUT", _MCP_DEFAULT_TIMEOUT))
    except ValueError:
        timeout = _MCP_DEFAULT_TIMEOUT
    try:
        proc = subprocess.run(  # noqa: S603 - cmd is fixed/operator-set, shell=False
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None  # claude CLI missing / probe too slow → stay silent, fail-open
    down = []
    for raw in (proc.stdout or "").splitlines():
        low = raw.lower()
        if any(m in low for m in _MCP_UNHEALTHY_MARKERS):
            name = _mcp_server_name(raw)
            if name not in down:
                down.append(name)
    if not down:
        return None
    return (
        "MCP health: {n} server(s) not connected — {names}. "
        "Fix/reconnect before relying on them (or the tool call will fail).".format(
            n=len(down), names=", ".join(down)
        )
    )


def _reporter_lines(project_dir, source):
    """Folded reporter lines (mcp_health @30, session_report @35, session_resume @40) — that emit
    order preserves the pre-fold output order. EMPTY on compact (all three formerly silenced
    mid-session). Inject-only: every producer isolated so one failing producer never drops the rest.
    """
    if source == "compact":
        return []
    lines = []
    try:  # mcp_health (was order 30)
        mh = _mcp_health_line()
        if mh:
            lines.append(mh)
    except Exception:
        pass
    try:  # session_report (was order 35) — STARTREPORT=0 silences cost/plans/state
        if (os.environ.get("STARTREPORT") or "1") != "0":
            for fn in (_cost_line, _plans_line, _state_line):
                try:
                    v = fn(project_dir)
                except Exception:
                    v = None
                if v:
                    lines.append(v)
    except Exception:
        pass
    try:  # session_resume (was order 40) — prev-session crumb + package manager
        lines.extend(_resume_lines(project_dir))
    except Exception:
        pass
    return lines


def main():
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")

    # Register the docstamp merge driver every session (idempotent, cheap, no output) — BEFORE the
    # concise/full branch split so it also runs on compact/resume. Kills the top-of-file stamp
    # conflict class in rebases/merges.
    _register_merge_driver(project_dir)

    # context-reinjection — source-aware branch. ONLY an explicit source of "compact"/"resume"
    # takes the concise-reminder path. Every other case — startup, clear, fork, any other explicit
    # value, AND an unreadable/absent source (empty/malformed stdin, missing field) — falls back to
    # the full [Session Context] dump (G3/GP1, flipped post-review per
    # crew/auditor-context-reinjection.md Finding 1): silently dropping the H4 GATE-0 behind-count
    # warning, the #117 stale-local-main warning, and HANDOFF surfacing on an unrecognized/
    # unreadable source is a worse failure mode than being verbose on an actual compact/resume that
    # somehow lost its source label — being "too safe" beats being silently blind to a stale branch.
    source = _read_source()
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
        try:
            reminder = _reminder_line(project_dir)
            if reminder:
                lines.append(reminder)
        except Exception:
            pass
        # folded reporters — on resume they emit (return [] on compact), matching the old separate
        # hooks that silenced only on source=="compact". Isolated try/except (inject-only).
        try:
            lines.extend(_reporter_lines(project_dir, source))
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

    # H4 — GATE-0 behind-count injector. Fully isolated try/except: a bug here must never crash
    # the hook or block the session (SessionStart is inject-only, never blocking).
    try:
        gate0 = _gate0_line(project_dir)
        if gate0:
            status_lines.append(gate0)
    except Exception:
        pass

    # #117 — GATE-0 code-freshness: warn when the LOCAL default-branch ref is stale vs origin/<branch>.
    # Isolated try/except (inject-only, never blocks).
    try:
        stale = _stale_local_main_line(project_dir)
        if stale:
            status_lines.append(stale)
    except Exception:
        pass

    # H12 — rules load check: a CLAUDE.md-imported rule that is missing or gitignored is silent
    # context loss (#194/#198). Isolated try/except (inject-only, never blocks).
    try:
        rules_line = _rules_load_line(project_dir)
        if rules_line:
            status_lines.append(rules_line)
    except Exception:
        pass

    # LSP preflight — warn when an enabled *-lsp plugin's language server is missing from PATH
    # (grep fallback silently in effect). Isolated try/except (inject-only, never blocks).
    try:
        lsp_line = _lsp_preflight_line(project_dir)
        if lsp_line:
            status_lines.append(lsp_line)
    except Exception:
        pass

    # S1 (plugin install hygiene) — claude_template only, skipped in the cloud. Isolated
    # try/except (inject-only, never blocks); any read error is silent (advisory).
    try:
        plugin_line = _plugin_behind_line(project_dir)
        if plugin_line:
            status_lines.append(plugin_line)
    except Exception:
        pass

    # session_prime_gate first-action instruction — loud line when the gate WILL block the first
    # mutation (managed + on primary OR not primed). Isolated try/except (inject-only, never blocks).
    try:
        pg_line = _prime_gate_line(project_dir)
        if pg_line:
            status_lines.append(pg_line)
    except Exception:
        pass

    # Project-specific status (customize this section)
    # Example: DB stats, file counts, pipeline progress

    # HANDOFF surfacing — isolated try/except so a bug here never crashes the inject-only hook.
    handoff = None
    try:
        handoff = _handoff_context(project_dir)
    except Exception:
        handoff = None

    # #7 — day-of-week reminder, opt-in via .claude/reminders.json. Isolated try/except
    # (inject-only, never blocks): a bug here must never crash SessionStart.
    try:
        reminder = _reminder_line(project_dir)
        if reminder:
            status_lines.append(reminder)
    except Exception:
        pass

    # seam-contract extraNotes — FULL-dump branch ONLY (the concise compact/resume path above
    # returns before reaching here and never runs seams — P3). Isolated try/except (inject-only).
    try:
        for note in _seam_extra_note_lines(project_dir):
            status_lines.append(note)
    except Exception:
        pass

    # §81 — concurrent-session warning + heartbeat lock (inject-only; each isolated so a bug here
    # never crashes SessionStart). Detect BEFORE writing our own lock so we never flag ourselves.
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

    # folded reporters (mcp_health / session_report / session_resume) — appended AFTER session_start's
    # own status lines so net output order matches the old separate hooks (they ran at order 30-45,
    # after session_start's order 10). Isolated try/except (inject-only, never blocks).
    try:
        for rl in _reporter_lines(project_dir, source):
            status_lines.append(rl)
    except Exception:
        pass

    print("\n".join(status_lines))
    if handoff:
        print("\n" + handoff)


if __name__ == "__main__":
    main()
