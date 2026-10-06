#!/usr/bin/env python3
# dependencies = []
"""Stop entry — the four CLOSE/P6 gates as modules over ONE transcript pass (hook consolidation PR 7).

Replaces close_issue_gate, close_gate, docs_gate, plan_gate; those files are now forwarders
(`main(only=<gate>)`) so old wiring and old tests still work. Every module runs (fail-open on its own);
ALL block reasons are joined into one {"decision":"block"}, and every notice / fail-open skip rides in
the SAME object's `systemMessage` (notices are NOT dropped when something blocks — R1 CRITICAL-3).
Always exit 0."""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))  # -P / PYTHONSAFEPATH drops the script dir (PR 5 C2)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from _git import run as _git_run  # noqa: E402 — #743 shared runner (breadcrumb on failure)

# A _lib import failure turns every gate OFF — announced on STDOUT (systemMessage), never
# stderr-only, so the fail-open is VISIBLE (R1 CRITICAL-2). The message is emitted in main().
LIB_OFF_MSG = None
try:
    from _lib.docs_map import is_doc, load as load_docs_map  # D1 — one docs map for docs_gate
    from _lib.test_cmd import _find_conf, _test_cmd
    from _lib.transcript import last_verdict, parse_ts, scan, verdict
except Exception as _e:  # noqa: BLE001
    LIB_OFF_MSG = f"stop_gate: _lib failed to load ({_e}) — every Stop gate is OFF; run setup.sh --update-hooks"
    print(LIB_OFF_MSG, file=sys.stderr)
    scan = None

# ---- close_gate texts (moved verbatim) --------------------------------------------------------
REFLECT_BLOCK_REASON = (
    "CLOSE gate ⛔ — this session merged a PR but never ran /dev-reflect (no "
    "`docs(lessons):` commit or dev-reflect invocation detected). Harvest wins + lessons "
    "into the project's lessons file before stopping, or state exactly: WORKFLOW:no-reflect. "
    "After satisfying this, continue with the next planned step — don't stop to ask for "
    "permission to proceed."
)
HANDOFF_WARN = (
    "CLOSE notice: this session merged a PR but the primary worktree's HANDOFF.md doesn't "
    "look like it was updated this session — run /handoff for session continuity."
)
VERIFY_BLOCK_REASON = (
    "CLOSE gate ⛔ — this session committed changes but no test/lint/validate run was detected. "
    "GATE-2 requires fresh evidence before 'done' — run /validate (or the project's test/lint "
    "command) this session, then stop. After satisfying this, continue with the next planned step "
    "— don't stop to ask for permission. If verification genuinely doesn't apply, state exactly: "
    "WORKFLOW:no-verify"
)

# ---- close_issue_gate text (moved verbatim) ---------------------------------------------------
CLOSE_ISSUE_REASON = (
    "CLOSE gate ⛔ — this session merged a PR but filed no GitHub issues for "
    "follow-ups/known gaps. Run `gh issue create` for each deferred item, or if "
    "there are genuinely none, state exactly: WORKFLOW:no-follow-ups. After "
    "satisfying this, continue with the next planned step — don't stop to ask for "
    "permission to proceed."
)

# ---- docs_gate text + classes (docs class now comes from _lib/docs_map.py, D1) ----------------
DOCS_BLOCK_REASON = (
    "P6 DOCUMENT gate ⛔ — this session committed code but no docs (docs/**/*.md or a top-level "
    "README.md). P6 is a HARD GATE: reconcile the docs the change made stale before stopping "
    "(run docs-impact-agent to find them, then /write), or state exactly: WORKFLOW:no-docs. "
    "This is a presence check, not a correctness check — docs-impact-agent is the judgment layer. "
    "After satisfying this, continue with the next planned step — don't stop to ask permission."
)
SOURCE_EXTS_DEFAULT = (
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".sh",
)

# ---- plan_gate text + patterns (moved verbatim) -----------------------------------------------
PLAN_PATH = "docs/superpowers/plans"
UNCHECKED_BOX_RE = re.compile(r"^\s*[-*]\s+\[ \]\s")
TEST_VERIFY_RE = re.compile(r"\b(test|verify|validate)\b", re.IGNORECASE)
PLAN_BLOCK_REASON = (
    "CLOSE gate ⛔ — this branch's plan has unproven steps: an unchecked `- [ ]` test/verify "
    "checkbox remains in docs/superpowers/plans/**. Per the Plan Contract (§5) an unchecked box "
    "means the step is unproven — run the test / `/validate`, tick the box once fresh evidence "
    "exists, then stop. After satisfying this, continue with the next planned step — don't stop to "
    "ask for permission. For a genuinely trivial plan, state: WORKFLOW:no-plan-check."
)

# ---- new verify-leg texts (byte-identical in both twins) --------------------------------------
VERIFY_FAIL_REASON = (
    "CLOSE gate ⛔ — the last test-suite run this session failed: `{cmd}` ({why}). Fix it and re-run "
    "the suite, then stop. If this RED is intentional (test-first COVER step), end with "
    "WORKFLOW:no-verify."
)
VERIFY_LOCK_REASON = (
    "CLOSE gate ⛔ — The suite didn't run — another session holds the test lock (exit 75). Re-run when "
    "it frees up. If verification genuinely doesn't apply, state exactly: WORKFLOW:no-verify"
)
VERIFY_UNKNOWN_NOTICE = (
    "CLOSE notice: the last suite run's result wasn't captured (it may have been killed, timed out, or "
    "is still running) — re-run /validate and confirm the suite is green before claiming done."
)
TIME_BUDGET_NOTICE = (
    "CLOSE notice: stop_gate couldn't finish reading this session's transcript (hit its internal time "
    "budget), so the CLOSE checks (verify included) are INCOMPLETE — re-run /validate and confirm the "
    "suite is green before claiming done; re-stop if a gate should have fired."
)
# git-call fail-open announcements — each names which CHECK was turned off, on stdout (R2 HIGH-3).
DOCS_GIT_SKIP = (
    "stop_gate: docs_gate couldn't list this session's commits (git error) — the P6 docs check was "
    "SKIPPED this turn."
)
PLAN_GIT_SKIP = (
    "stop_gate: plan_gate couldn't diff this branch against the trunk (git error) — the plan-checkbox "
    "check was SKIPPED this turn."
)
HANDOFF_GIT_SKIP = (
    "stop_gate: close_gate couldn't locate the primary worktree (git error) — the HANDOFF.md staleness "
    "check was SKIPPED this turn."
)
PLAN_BUDGET_SKIP = (
    "stop_gate: plan_gate SKIPPED — the time budget was spent before its git diff could run; re-stop "
    "to run the plan-checkbox check, or confirm the plan's test/verify boxes are ticked."
)
GIT_BUDGET_S = 40.0  # skip the git-heavy gates once this much wall-time is gone, so git can't push the
                     # hook past the 60 s harness kill (R2 MEDIUM-5). Override: STOP_GATE_GIT_BUDGET_S.
_UNSET = object()


# ---- close_gate helpers (moved verbatim) ------------------------------------------------------
def _primary_worktree(cwd, ctx=None):
    out = _git_run("close_gate", cwd, ["git", "worktree", "list", "--porcelain"], timeout=5)
    if out is None:
        if ctx is not None:
            ctx.git_skips.append(HANDOFF_GIT_SKIP)  # gate-disabling git failure → announce (R2 HIGH-3)
        return None
    for line in out.splitlines():
        if line.startswith("worktree "):
            return line[len("worktree "):].strip()
    return None


def _handoff_stale(cwd, first_ts, ctx=None):
    if first_ts is None:
        return False  # can't determine -> don't warn on an unknown
    primary = _primary_worktree(cwd, ctx)
    if not primary:
        return False
    handoff = os.path.join(primary, "HANDOFF.md")
    try:
        mtime = os.path.getmtime(handoff)
    except OSError:
        return True  # HANDOFF.md doesn't exist at all -> stale
    mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return mtime_dt < first_ts


def _load_snapshot(cwd, session_id):
    """Compaction-evidence snapshot written by precompact_evidence.py (limitation #36).

    Returns (flags_dict, first_ts, last_suite) — ({}, None, None) when absent/corrupt/mismatched.
    `last_suite` carries the pre-compaction suite OUTCOME so a FAILED run isn't read as passing (R1 HIGH-4)."""
    empty = ({}, None, None)
    if not session_id or not isinstance(session_id, str):
        return empty
    snap_path = os.path.join(
        cwd or os.getcwd(), ".claude", "session-logs",
        "compact-" + re.sub(r"[^A-Za-z0-9._-]", "_", session_id) + ".json",
    )
    try:
        with open(snap_path, "r", encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return empty
    if not isinstance(snap, dict) or snap.get("session_id") != session_id:
        return empty
    flags = snap.get("flags")
    ls = snap.get("last_suite")
    return (flags if isinstance(flags, dict) else {}, parse_ts(snap.get("first_ts")),
            ls if isinstance(ls, dict) else None)


# ---- docs_gate helpers — docs class comes from the one docs map (_lib/docs_map.py, D1) ---------
def _docs_classify(path, globs, historical):
    norm = path.replace("\\", "/")
    if is_doc(norm, globs, historical):
        return "DOCS"
    if os.path.splitext(norm)[1] in SOURCE_EXTS_DEFAULT:
        return "SOURCE"
    return "NEUTRAL"  # unknown extension -> never block on uncertainty


def _docs_should_block(paths, globs, historical):
    classes = [_docs_classify(p, globs, historical) for p in paths]
    return "SOURCE" in classes and "DOCS" not in classes


def _session_committed_files(cwd, first_ts, ctx=None):
    """Files touched by commits reachable in `cwd` since `first_ts`. Empty on any git error or
    unknown start time (fail-open); a git FAILURE is announced (R2 HIGH-3)."""
    if first_ts is None:
        return []
    out = _git_run("docs_gate", cwd, ["git", "log", "--since=" + first_ts.isoformat(),
                                      "--name-only", "--format="], timeout=5)
    if out is None:
        if ctx is not None:
            ctx.git_skips.append(DOCS_GIT_SKIP)
        return []
    seen = set()
    files = []
    for line in out.splitlines():
        p = line.strip()
        if p and p not in seen:
            seen.add(p)
            files.append(p)
    return files


# ---- plan_gate helpers (moved verbatim; local _run renamed _plan_run) -------------------------
def _plan_run(cwd, args, timeout=8):
    return _git_run("plan_gate", cwd, args, timeout=timeout)


def _current_branch(cwd):
    out = _plan_run(cwd, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if out else None


def _resolve_trunk(cwd):
    """Best-effort trunk ref to diff against: origin's default branch, else local main/master."""
    ref = _plan_run(cwd, ["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
    if ref:
        parts = ref.strip().split("/")
        if len(parts) >= 2:
            return "/".join(parts[-2:])
    for candidate in ("origin/main", "origin/master", "main", "master"):
        if _plan_run(cwd, ["git", "rev-parse", "--verify", "--quiet", candidate]) is not None:
            return candidate
    return None


def _branch_added_plans(cwd, ctx=None):
    """Plan files ADDED on THIS branch since it diverged from trunk (branch-scoped, merge-base). A
    FAILURE of the gate-disabling calls (merge-base, diff) is announced; the _resolve_trunk /
    _current_branch rev-parse probes are left alone (a non-zero there is EXPECTED) (R2 HIGH-3)."""
    branch = _current_branch(cwd)
    trunk = _resolve_trunk(cwd)
    if not branch or not trunk or trunk == branch:
        return []
    base = _plan_run(cwd, ["git", "merge-base", "HEAD", trunk])
    if not base:
        if ctx is not None:
            ctx.git_skips.append(PLAN_GIT_SKIP)
        return []
    base = base.strip()
    out = _plan_run(
        cwd,
        ["git", "diff", "--name-only", "--diff-filter=A", f"{base}..HEAD", "--", PLAN_PATH],
    )
    if out is None:
        if ctx is not None:
            ctx.git_skips.append(PLAN_GIT_SKIP)
        return []
    return [p.strip() for p in out.splitlines() if p.strip()]


def _has_unproven_step(cwd, rel_path):
    """True iff the working-tree plan file has ≥1 unchecked `- [ ]` test/verify checkbox."""
    try:
        with open(os.path.join(cwd or "", rel_path), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if UNCHECKED_BOX_RE.match(line) and TEST_VERIFY_RE.search(line):
                    return True
    except OSError:
        return False  # unreadable -> can't prove unproven -> don't block
    return False


# ---- lazy per-Stop context (one scan + one snapshot, shared by every module) -------------------
def _git_budget_s():
    ov = os.environ.get("STOP_GATE_GIT_BUDGET_S")
    if ov:
        try:
            return float(ov)
        except ValueError:
            pass
    return GIT_BUDGET_S


class _Ctx:
    def __init__(self, data):
        self.data = data
        self.cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
        self._scan = self._snap = _UNSET
        self.scan_error = None  # ("unreadable"|"error", exc) — announced on stdout in main (R1 C1)
        self.git_skips = []     # gate-disabling git-call failures, announced on stdout (R2 HIGH-3)
        self._start = time.monotonic()
        self._git_budget = _git_budget_s()

    def budget_spent(self):
        """True once enough wall-time is gone that a git-heavy gate risks the 60 s harness kill —
        the scan can burn up to its own budget, so git must bow out past this line (R2 MEDIUM-5)."""
        return (time.monotonic() - self._start) > self._git_budget

    def scan(self):
        """One pass, shared by every module. None when there is no readable transcript; on failure
        records scan_error so main can ANNOUNCE which gates were skipped (never silent, R1 C1)."""
        if self._scan is _UNSET:
            self._scan = None
            tp = self.data.get("transcript_path")
            if tp and isinstance(tp, str):
                try:
                    conf = _find_conf(self.cwd)
                    self._scan = scan(tp, _test_cmd(conf) if conf else None)
                except OSError as e:
                    self.scan_error = ("unreadable", e)
                except Exception as e:  # noqa: BLE001 — a scan bug skips the scan-gates; announce it
                    self.scan_error = ("error", e)
        return self._scan

    def snapshot(self):
        if self._snap is _UNSET:
            self._snap = _load_snapshot(self.cwd, self.data.get("session_id"))
        return self._snap


def _short(cmd):
    c = " ".join(cmd.split())
    return c if len(c) <= 80 else c[:77] + "…"


def _judge_suite(outcome, exit_code, command):
    """Map a suite outcome → ('block'|'notice', text) or None (pass)."""
    if outcome == "lock":
        return ("block", VERIFY_LOCK_REASON)
    if outcome == "fail":
        why = f"exit {exit_code}" if exit_code is not None else "failures in its output"
        return ("block", VERIFY_FAIL_REASON.format(cmd=_short(command), why=why))
    if outcome == "unknown":
        return ("notice", VERIFY_UNKNOWN_NOTICE)  # result not captured — surface, don't block (R1 HIGH-5/7, R2 HIGH-2)
    return None  # pass


def _snap_judged(snap_last):
    """The compaction snapshot's suite verdict, or None. last_suite stores only a DEFINITE outcome,
    so this is a block (fail/lock) or None (pass/absent) — never a notice."""
    if isinstance(snap_last, dict) and snap_last.get("outcome"):
        return _judge_suite(snap_last.get("outcome"), snap_last.get("exit"), snap_last.get("command", "the suite"))
    return None


def _verify(s, snap, snap_last):
    """Returns a list of (kind, text). The most-recent DEFINITE live suite wins (a later `unknown`
    run can't hide its FAIL — R2 HIGH-2); with no live definite result, the pre-compaction snapshot's
    FAIL still blocks before any unknown notice (R1 HIGH-4, R3 H-A); else 'a check ran' allows; else
    BLOCK (no run)."""
    if not (s.made_commit or snap.get("made_commit") is True):
        return []
    if "WORKFLOW:no-verify" in s.tokens or snap.get("no_verify") is True:
        return []
    if getattr(s, "timed_out", False):
        # the scan was truncated — don't judge the PARTIAL read, but a COMPLETE snapshot FAIL still
        # blocks; otherwise main's TIME_BUDGET_NOTICE carries the INCOMPLETE warning (R3 H-A / MEDIUM-4).
        sr = _snap_judged(snap_last)
        return [sr] if sr else []
    mr, last_unknown = verdict(s)
    if mr is not None:
        r = _judge_suite(mr.outcome, mr.exit, mr.command)
        if r:
            return [r]  # a definite fail/lock blocks even behind a later unknown run (R2 HIGH-2)
        return [("notice", VERIFY_UNKNOWN_NOTICE)] if last_unknown else []  # pass, but a later re-run wasn't seen
    # no live definite result → the snapshot's FAIL must block BEFORE the unknown notice (R3 H-A)
    sr = _snap_judged(snap_last)
    if sr:
        return [sr]
    if last_unknown:
        return [("notice", VERIFY_UNKNOWN_NOTICE)]  # live suite(s) ran but every result was unknown, snapshot clean
    if last_verdict(s)[1] or snap.get("ran_test") is True:
        return []  # lint / legacy check ran, no suite verdict to judge
    return [("block", VERIFY_BLOCK_REASON)]


def _close_issue_gate(ctx):
    s = ctx.scan()
    if s is None:
        return []
    snap = ctx.snapshot()[0]
    merged = s.did_merge or snap.get("did_merge") is True
    filed = s.filed_issue or snap.get("filed_issue") is True
    declared = "WORKFLOW:no-follow-ups" in s.tokens or snap.get("declared_none") is True
    return [("block", CLOSE_ISSUE_REASON)] if merged and not filed and not declared else []


def _close_gate(ctx):
    s = ctx.scan()
    if s is None:
        return []
    snap, snap_ts, snap_last = ctx.snapshot()
    out = []
    merged = s.did_merge or snap.get("did_merge") is True
    reflected = (s.ran_reflect or snap.get("ran_reflect") is True
                 or "WORKFLOW:no-reflect" in s.tokens or snap.get("no_reflect") is True)
    if merged and not reflected:
        out.append(("block", REFLECT_BLOCK_REASON))
    out.extend(_verify(s, snap, snap_last))
    # The handoff WARN is kept EVEN when a gate blocks (notices ride in the same object, R1 C3).
    if merged:
        first = min((t for t in (s.first_ts, snap_ts) if t is not None), default=None)
        if _handoff_stale(ctx.cwd, first, ctx):
            out.append(("notice", HANDOFF_WARN))
    return out


def _docs_gate(ctx):
    s = ctx.scan()
    if s is None or not s.made_commit or "WORKFLOW:no-docs" in s.tokens:
        return []
    files = _session_committed_files(ctx.cwd, s.first_ts, ctx)
    if not files:
        return []
    globs, historical = load_docs_map(ctx.cwd)
    return [("block", DOCS_BLOCK_REASON)] if _docs_should_block(files, globs, historical) else []


def _plan_gate(ctx):
    s = ctx.scan()  # runs with NO transcript too (PL8) — the bypass is then simply absent
    if s is not None and "WORKFLOW:no-plan-check" in s.raw_tokens:
        return []
    if ctx.budget_spent():
        return [("notice", PLAN_BUDGET_SKIP)]  # git-heavy; the 60 s harness kill would hit mid-diff (R2 MEDIUM-5)
    for rel_path in _branch_added_plans(ctx.cwd, ctx):
        if _has_unproven_step(ctx.cwd, rel_path):
            return [("block", PLAN_BLOCK_REASON)]
    return []


MODULES = (
    ("close_issue_gate", _close_issue_gate),
    ("close_gate", _close_gate),
    ("docs_gate", _docs_gate),
    ("plan_gate", _plan_gate),
)


_SCAN_GATES = ("close_issue_gate", "close_gate", "docs_gate")


STDIN_BAD_MSG = (
    "stop_gate: unreadable Stop payload (bad JSON or not an object) — no CLOSE gate ran this turn."
)
CRASH_MSG = (
    "stop_gate: crashed unexpectedly — no CLOSE gate ran this turn; re-stop to retry (fail-open)."
)


def main(only=None):
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        # unreadable stdin leaves every gate silently OFF — make the fail-open VISIBLE (R2 MEDIUM-6)
        print(json.dumps({"systemMessage": STDIN_BAD_MSG}))
        return 0
    if not isinstance(data, dict):
        print(json.dumps({"systemMessage": STDIN_BAD_MSG}))
        return 0
    if scan is None:  # a _lib import failure — announce on STDOUT, never stderr-only (R1 C2)
        if LIB_OFF_MSG:
            print(json.dumps({"systemMessage": LIB_OFF_MSG}))
        return 0
    ctx = _Ctx(data)
    blocks, notices, skips = [], [], []
    for name, fn in MODULES:
        if only and name != only:
            continue
        try:
            for kind, text in fn(ctx):
                (blocks if kind == "block" else notices).append(text)
        except Exception as e:  # noqa: BLE001 — a crashing module is SKIPPED, announced, not silent (R1 C3)
            msg = f"stop_gate: {name} skipped ({e})"
            print(msg, file=sys.stderr)
            skips.append(msg)
    # An unreadable/failed transcript turns the scan gates OFF — announce it on stdout (R1 C1).
    if ctx.scan_error is not None and (only is None or only in _SCAN_GATES):
        kind, e = ctx.scan_error
        verb = "unreadable" if kind == "unreadable" else "scan failed"
        msg = f"stop_gate: transcript {verb} ({e}) — close_issue/close/docs gates SKIPPED"
        print(msg, file=sys.stderr)
        skips.append(msg)
    skips.extend(ctx.git_skips)  # gate-disabling git failures announced on stdout (R2 HIGH-3)
    sc = ctx._scan
    if sc is not None and getattr(sc, "timed_out", False):
        skips.append(TIME_BUDGET_NOTICE)
    sys_parts = notices + skips
    out = {}
    if blocks:
        out["decision"] = "block"
        out["reason"] = "\n\n".join(blocks)
    if sys_parts:
        out["systemMessage"] = "\n".join(sys_parts)
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — make the crash VISIBLE on stdout, never a silent exit 0 (R3)
        try:
            print(json.dumps({"systemMessage": CRASH_MSG}))
        except Exception:  # noqa: BLE001
            pass
        sys.exit(0)
