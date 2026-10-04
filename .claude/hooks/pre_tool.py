#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse hook — the single entry (hook consolidation PR 6). Reads stdin once, builds one ctx, and
runs every legacy group in a fixed order: PR 5's per-tool guard table (`pre_tool_use`), then the 8
folded gates (session_prime, grill, tdd, nocommit, test_lock, plan_interview, parallel, stale_base —
stale_base last, its fetch is the only network call). Full mode JOINS all DENY reasons into one deny;
`--only <hook>` reproduces one retired hook's old output byte-for-byte so old wiring keeps working.
Guards/gates are imported lazily, and the commit gates only when `"commit" in command` (speed budget)."""

import collections
import importlib
import json
import math
import os
import re
import subprocess
import sys
import time
import types

# Wall-clock budget for the full-mode group loop (#979/§TIMEOUT). Well under the PreToolUse entry's
# own `timeout` in hooks.json, so the loop STOPS and emits the denies collected so far rather than
# being killed mid-run (a kill drops them → fail-open). Override for tests via PRE_TOOL_BUDGET_MS.
def _budget_s():
    # #979/item4: empty, non-numeric, ≤0, or non-finite PRE_TOOL_BUDGET_MS all fall back to 10 s —
    # a 0/negative/garbage budget must NOT make the hook skip every check (fail-open).
    try:
        v = float(os.environ.get("PRE_TOOL_BUDGET_MS") or "10000")
    except (TypeError, ValueError):
        return 10.0
    if not math.isfinite(v) or v <= 0:
        return 10.0
    return v / 1000.0

# The guard packages sit next to this file. Pin that dir onto sys.path explicitly: under -P /
# PYTHONSAFEPATH Python drops the script dir, and every guard import would fail open.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Paths that agents cannot write to (customize per project)
READONLY_PATHS = ["/source/"]

# Per tool, in today's order. Bash = the old inline readonly/.env/DB checks, then the old guard
# table (H1 test-lock … H11 secret-read). (module, function) — imported only when that tool fires.
_DENY_GUARDS = {
    "Agent": (("model", "check"),),
    "Task": (("model", "check"),),
    "Bash": (
        ("readonly", "check_bash"), ("env_write", "check"), ("db_ops", "check"),
        ("test_lock", "check_runner"), ("conventional_commit", "check"), ("secret_scan", "check"),
        ("danger", "check"), ("protected_branch", "check"), ("worktree_cwd", "check"),
        ("shared_checkout", "check"), ("giant_file", "check"), ("secret_file", "check"),
        ("secret_read", "check_bash"),
    ),
    "Write": (("readonly", "check_write"), ("template_owned", "check")),
    "Edit": (("readonly", "check_write"), ("template_owned", "check")),
    "Read": (("secret_read", "check_read"),),
}
# H5/H6 + prune — INJECT-ONLY, Bash only, after every deny-capable guard; one additionalContext.
_BASH_REMINDERS = (("reminders", "pr_review"), ("reminders", "docs_staleness"),
                   ("reminders", "worktree_prune"))


def __getattr__(name):
    """Lazy back-compat re-export: tests/test_pretooluse_shared_checkout.sh imports the SCG helpers
    off this module (`import pre_tool_use as p; p._git_timeout()`). Resolved only on access, so a
    normal hook run never pays for the extra import."""
    if name in ("_git_timeout", "_is_primary_checkout", "_other_live_session"):
        return getattr(importlib.import_module("guards.shared_checkout"), name)
    raise AttributeError(name)


def _load(module, fn, off):
    """A guard function, or None if its module can't load (or lacks `fn`) — one broken or missing
    module turns only THAT guard off, never the hook (spec § Error handling). The guard is recorded
    in `off` so the user is TOLD (systemMessage), not just stderr, which an exit-0 hook never shows."""
    try:
        f = getattr(importlib.import_module("guards." + module), fn, None)
        if not callable(f):
            raise TypeError(f"missing export {fn}")
        return f
    except Exception as exc:  # noqa: BLE001 - never brick a session on a bad install
        sys.stderr.write(f"[pre_tool] guards/{module} failed to load ({exc!r}) — that guard is OFF\n")
        off.append(module)
        return None


# ==== seam-contract (repo-local config; non-guard — G8) =========================================
# docs/superpowers/specs/2026-08-12-seam-contract-design.md — two of the three optional seam files
# are read HERE (the third, session-start.json, belongs to the SessionStart hook). Seams are
# strictly ADDITIVE: they can inject a warning or TIGHTEN the readonly list, never relax a block —
# the blocking guards (H1/H2/H3/H7/H8/H9/H10/DB, and the baseline readonly check itself) read no
# seam file, which the §62 G8 test pins by grepping everything OUTSIDE this fenced section.
# Absent/malformed/wrong-typed seams and unrunnable probes are a SILENT no-op (a broken seam must
# never break a session or block a tool call). Argv arrays only (no shell), probe timeout 20s,
# match patterns capped at 500 chars (G2), cwd = project dir. Tests point at alternate seam FILES
# via the CLAUDE_SEAM_PRE_TOOL_NOTIFY / CLAUDE_SEAM_READONLY_PATHS env overrides.
SEAM_PROBE_TIMEOUT_MS = 20000
SEAM_MAX_PATTERN_LEN = 500


def _seam_load_json(env_name, project_dir, filename):
    """Parsed JSON of the seam file (env-override path wins), or None — silent on absent,
    unreadable, or malformed (inject-only discipline; never raises)."""
    try:
        seam_path = os.environ.get(env_name) or os.path.join(
            project_dir or ".", ".claude", filename
        )
        if not os.path.isfile(seam_path):
            return None
        with open(seam_path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _seam_readonly_paths(project_dir):
    """readonly-paths.json — `["path/", …]` APPENDED to READONLY_PATHS by the caller (tighten-only:
    the baseline list is code, a seam can never remove an entry). [] on any malformation."""
    data = _seam_load_json("CLAUDE_SEAM_READONLY_PATHS", project_dir, "readonly-paths.json")
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, str) and p]


def _seam_notify_warnings(command, project_dir):
    """pre-tool-notify.json — `[{"match","probe","warn"}]` evaluated against a BASH command only.
    A probe that RUNS and FAILS (non-zero exit) injects the warn — that's the signal; a probe that
    cannot RUN (missing binary, spawn error, timeout) is a no-op (fail-open, matching ableton's
    forked guard). NEVER returns a block decision — warns ride the H5/H6 additionalContext channel.
    """
    data = _seam_load_json("CLAUDE_SEAM_PRE_TOOL_NOTIFY", project_dir, "pre-tool-notify.json")
    if not isinstance(data, list):
        return []
    warns = []
    for entry in data:
        try:
            if not isinstance(entry, dict):
                continue
            match = entry.get("match")
            probe = entry.get("probe")
            warn = entry.get("warn")
            if not (isinstance(match, str) and 0 < len(match) <= SEAM_MAX_PATTERN_LEN):
                continue  # over-cap patterns ignored (G2 pathological-regex cap)
            if not (isinstance(warn, str) and warn):
                continue
            if not (isinstance(probe, list) and probe and all(isinstance(a, str) for a in probe)):
                continue  # argv array of strings only — never a shell string
            if not re.search(match, command):
                continue
            result = subprocess.run(
                probe, capture_output=True, text=True, cwd=project_dir or None,
                timeout=SEAM_PROBE_TIMEOUT_MS / 1000.0, check=False,
            )
            if result.returncode != 0:
                warns.append(warn)
        except Exception:
            continue  # bad regex / missing binary / timeout → this entry is a silent no-op
    return warns
# ==== end seam-contract =========================================================================


_G = collections.namedtuple("_G", "name tools commit_only needs_event form bypass tel_reason guard")
# The retired hooks after pre_tool_use, in registry order — stale_base LAST: its fetch is the only
# network call (≤5 s cap), so everything local has already decided. `commit_only`: every commit
# gate's trigger needs the literal word `commit`, so other Bash calls never import them (speed).
_GROUPS = (
    _G("session_prime_gate", ("Edit", "Write", "NotebookEdit", "Bash"), False, False, "dual", None, None,
       ("session_prime", "check")),
    _G("grill_gate", ("Bash",), True, False, "dual", "WORKFLOW:no-grill", None, ("grill", "check")),
    _G("tdd_gate", ("Bash",), True, False, "dual", "WORKFLOW:no-tdd", None, ("tdd", "check")),
    _G("nocommit_guard", ("Bash",), True, False, "dual", "WORKFLOW:no-nocommit", None, ("nocommit", "check")),
    _G("test_lock_enforce", ("Bash",), False, True, "tle", "CT_ALLOW_UNLOCKED_TESTS",
       "suite runs are serialized per-repo (test-lock)", ("test_lock", "check_test_cmd")),
    _G("plan_interview_gate", ("Bash",), True, False, "dual", "WORKFLOW:no-interview", None,
       ("plan_interview", "check")),
    _G("parallel_gate", ("Bash",), True, False, "dual", "WORKFLOW:no-parallel", None, ("parallel", "check")),
    _G("stale_base_guard", ("Bash",), True, False, "dual", "WORKFLOW:no-rebase-check", None,
       ("stale_base", "check")),
)
_BY_NAME = {g.name: g for g in _GROUPS}


def _ctx(data):
    """PR 5's ctx (same fields, same defaults) + the raw payload for the moved gates."""
    tool_name = data.get("tool_name", "")
    # #979/M2: a payload with `"tool_input": null` (the key present, value null) makes .get return
    # None, and None.get(...) is an AttributeError that used to crash the hook. Coerce a missing /
    # null / non-dict tool_input to {} and a non-str command to "" — malformed input must fail OPEN,
    # never crash a PreToolUse gate.
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd", "") or "."
    readonly_paths = list(READONLY_PATHS)
    try:
        readonly_paths += _seam_readonly_paths(project_dir)
    except Exception:  # noqa: BLE001 - the seam only ever APPENDS; failure → the baseline
        readonly_paths = list(READONLY_PATHS)
    command = tool_input.get("command", "") if tool_name == "Bash" else ""
    if not isinstance(command, str):
        command = ""
    return types.SimpleNamespace(data=data, tool_name=tool_name, tool_input=tool_input, command=command,
                                 cwd=data.get("cwd", ""), project_dir=project_dir,
                                 readonly_paths=readonly_paths, notes=[], stderr_notes=[],
                                 skip_stale_fetch=False)


def _ptu_denies(ctx, decide, off, first_only):
    """The pre_tool_use group (PR 5's table): first deny (legacy) or every deny (full mode)."""
    out = []
    for module, fn in _DENY_GUARDS.get(ctx.tool_name, ()):
        check = _load(module, fn, off)
        reason = decide.run(check, ctx, off, module) if check else None
        if reason:
            out.append(reason)
            if first_only:
                break
    return out


def _emit_allow(ctx, decide, off, full=False):
    """PR 5's allow-path stdout, byte-identical: Bash reminders + notify warns, and any OFF
    systemMessage — ONE JSON object (so a degraded guard is visible on stdout in full mode too).
    In FULL mode the fail-open breadcrumbs (ctx.stderr_notes) also ride the systemMessage; the
    `--only` forwarder path flushes those to stderr instead (byte-parity, done by the caller)."""
    out = {}
    if ctx.tool_name == "Bash":
        reminders = []
        for module, fn in _BASH_REMINDERS:
            check = _load(module, fn, off)
            r = decide.run(check, ctx, off, module) if check else None
            if r:
                reminders.append(r)
        # Notify warns join the same additionalContext payload and can never block.
        try:
            reminders.extend(_seam_notify_warnings(ctx.command, ctx.project_dir))
        except Exception:  # noqa: BLE001
            pass
        if reminders:
            out["hookSpecificOutput"] = {
                "hookEventName": "PreToolUse",
                "additionalContext": "\n".join(reminders),
            }
    parts = []
    base = _allow_sysmsg(ctx, decide, off)
    if base is not None:
        parts.append(base)
    if full and getattr(ctx, "stderr_notes", None):
        parts.append("\n".join(ctx.stderr_notes))
    if parts:
        out["systemMessage"] = "\n".join(parts)
    if out:
        print(json.dumps(out))  # noqa: T201
    return 0


def _append_git_notes(ctx):
    """After the guards have run, surface any memoized git READ that failed this call (#979/M-H1):
    the guard fail-opened (allowed without verifying) and the failure was invisible on exit-0 stdout.
    Rides ctx.stderr_notes → stdout in full mode, stderr on the `--only` forwarder path."""
    try:
        from _lib import git
        labels = list(dict.fromkeys(git.failed_labels))
        if labels:
            ctx.stderr_notes.append(
                "pre_tool: git state unavailable for " + ", ".join(labels)
                + " (guard fail-open — not verified this call)")
    except Exception:  # noqa: BLE001 - a note is best-effort; never let it change the decision
        pass


def _flush_stderr_notes(ctx):
    """The `--only` forwarder path renders fail-open breadcrumbs to STDERR (byte-parity with the
    retired standalones, which wrote them there); full mode folds them into stdout instead."""
    for note in getattr(ctx, "stderr_notes", ()):
        sys.stderr.write(note + "\n")


def _allow_sysmsg(ctx, decide, off):
    """The combined stdout systemMessage for an ALLOW: OFF-guard notice (PR 5) + any guard notes a
    guard appended to ctx.notes on the allow path (#915 parallel_gate PG32/PG33 breadcrumbs). None
    when there's nothing to say — the allow then stays byte-silent as before."""
    parts = []
    if off:
        parts.append(decide.off_message(off))
    if getattr(ctx, "notes", None):
        parts.append("\n".join(ctx.notes))
    return "\n".join(parts) if parts else None


def _group_check(ctx, decide, off, g):
    if ctx.tool_name not in g.tools:
        return None
    # The commit prefilter must survive quote- AND backslash-obfuscation: the commit gates normalize
    # `git c"o"mmit` / `git com\mit` to `git commit`, so a raw-substring test would drop that deny
    # (#979/L1; harness BYTE/UNION).
    if g.commit_only and "commit" not in ctx.command.replace('"', '').replace("'", '').replace('\\', ''):
        return None
    if g.needs_event and ctx.data.get("hook_event_name") != "PreToolUse":
        return None
    check = _load(g.guard[0], g.guard[1], off)
    r = decide.run(check, ctx, off, g.guard[0]) if check else None
    if not r:
        return None
    return r if isinstance(r, tuple) else (r, g.bypass)


def _legacy(ctx, decide, off, name):
    """`--only <hook>`: that one retired hook, in ITS old output form, byte for byte. Fail-open
    breadcrumbs (ctx.stderr_notes) flush to STDERR here, matching the retired standalones."""
    if name == "pre_tool_use":
        denies = _ptu_denies(ctx, decide, off, first_only=True)
        _append_git_notes(ctx)
        _flush_stderr_notes(ctx)
        if denies:
            decide.deny(denies[0], ctx.command, off, ctx.notes)  # exits 2 — PR 5's form
        return _emit_allow(ctx, decide, off)
    g = _BY_NAME.get(name)
    if g is None:
        # #979/M4: surface an unknown --only on stdout (stderr is invisible on exit 0).
        print(json.dumps({  # noqa: T201
            "systemMessage": f"pre_tool: unknown --only {name!r} — nothing checked"}))
        return 0
    r = _group_check(ctx, decide, off, g)
    _append_git_notes(ctx)
    _flush_stderr_notes(ctx)
    if not r:
        # Old gate exited 0 silently on allow — keep that byte-identical UNLESS the guard left an
        # allow-path note (parallel_gate PG32/PG33) or a guard went OFF, which the standalone emitted
        # as a stdout systemMessage too.
        msg = _allow_sysmsg(ctx, decide, off)
        if msg is not None:
            print(json.dumps({"systemMessage": msg}))  # noqa: T201
        return 0
    decide.record(g.name, g.tel_reason or r[0], r[1])
    if g.form == "tle":
        decide.deny_json(r[0])
        return 0
    decide.block_dual(r[0], off, ctx.notes)  # exits 2


def _full(ctx, decide, off):
    """The wiring: every group runs; ALL deny reasons join into ONE deny (no fix-one-hit-the-next).
    #979/§TIMEOUT: stale_base (the only network call) is skipped once something ELSE already denies,
    and a wall-clock budget stops the loop before the entry's hard timeout could kill it mid-run and
    drop the collected denies. Fail-open breadcrumbs ride stdout in full mode."""
    start = time.monotonic()
    budget = _budget_s()
    # #979/item1: a HARD DEADLINE, not just a between-group check. Every git subprocess (the shared
    # runner + session_prime/danger's direct calls) is clamped to the remaining budget, so no single
    # group can overrun and let the harness kill the hook mid-run (a kill drops the collected deny).
    try:
        import _git
        _git.set_deadline(start + budget)
    except Exception:  # noqa: BLE001 - the clamp is best-effort; never block on it
        pass
    reasons = []
    ptu = _ptu_denies(ctx, decide, off, first_only=False)
    if ptu:
        decide.record("pre_tool_use", ptu[0])
        reasons += ptu
    for idx, g in enumerate(_GROUPS):
        if time.monotonic() - start > budget:
            remaining = [x.name for x in _GROUPS[idx:]]
            ctx.stderr_notes.append(
                f"pre_tool: time budget ({budget:.1f}s) exceeded — skipped remaining checks: "
                + ", ".join(remaining))
            break
        # Once a block is already pending, skip stale_base's network FETCH (its only slow/hanging
        # call) but STILL run its local overlap check — so its deny is never dropped (joined-deny /
        # union parity; the guard emits the gated note itself only when it actually runs). #979/item1+3.
        if g.name == "stale_base_guard" and reasons:
            ctx.skip_stale_fetch = True
        r = _group_check(ctx, decide, off, g)
        if r:
            decide.record(g.name, g.tel_reason or r[0], r[1])
            reasons.append(r[0])
    _append_git_notes(ctx)
    if reasons:
        text = reasons[0] if len(reasons) == 1 else (
            f"Blocked by {len(reasons)} checks:\n\n"
            + "\n\n".join(f"{i}. {r}" for i, r in enumerate(reasons, 1)))
        if ptu:
            from _lib.shell import _chained_ops_warning
            text += _chained_ops_warning(ctx.command)
        decide.block_dual(text, off, ctx.notes + ctx.stderr_notes)  # exits 2
    return _emit_allow(ctx, decide, off, full=True)


_BAD_STDIN_FULL = "pre_tool: unparseable/non-object stdin — ALL guards OFF"


def main(only=None):
    # Bad/empty stdin must not crash a PreToolUse hook. Fail OPEN on unparseable input.
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError) as exc:
        # `--only parallel_gate` reproduces the retired parallel_gate's byte-visible parse diagnostic
        # (#915/#3, incl. the exc repr). Full mode (#979/M3) says the WHOLE hook is OFF instead of
        # borrowing one guard's wording. Every other `--only <hook>` stayed silent — keep it silent.
        if only == "parallel_gate":
            print(json.dumps({"systemMessage":  # noqa: T201
                              f"parallel_gate: internal error {exc!r} — plan NOT collision-checked"}))
        elif only is None:
            print(json.dumps({"systemMessage": _BAD_STDIN_FULL}))  # noqa: T201
        return 0
    if not isinstance(data, dict):
        # Valid JSON but not an object. #979/M3: full mode now surfaces it (was silently allowed);
        # the `--only` forwarders (parallel_gate included) stayed silent here — byte-parity.
        if only is None:
            print(json.dumps({"systemMessage": _BAD_STDIN_FULL}))  # noqa: T201
        return 0
    try:
        from _lib import decide
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[pre_tool] _lib failed to load ({exc!r}) — every guard is OFF; "
                         "run setup.sh --update-hooks\n")
        # stderr on an exit-0 PreToolUse is never shown — say it where the user sees it.
        print(json.dumps({"systemMessage": "pre_tool: _lib missing/broken — ALL guards OFF; "  # noqa: T201
                          "run setup.sh --update-hooks"}))
        return 0
    # #979/M2: anything past this point runs guard code. A guard runner is already fail-open per
    # guard, but a crash in the dispatch itself (e.g. a malformed payload a guard trips on) must not
    # brick the call — catch it and fail OPEN with a visible notice. A real deny raises SystemExit
    # (decide.deny / block_dual call sys.exit), which is NOT an Exception, so it propagates untouched.
    try:
        decide.set_context(data.get("tool_name", ""), data.get("session_id", ""))
        ctx = _ctx(data)
        off = []  # guards that failed to load or threw this call — surfaced via systemMessage
        return _legacy(ctx, decide, off, only) if only is not None else _full(ctx, decide, off)
    except Exception as exc:  # noqa: BLE001 - never brick a PreToolUse call on an unexpected error
        print(json.dumps({"systemMessage":  # noqa: T201
                          f"pre_tool: crashed ({exc!r}) — ALL guards OFF this call"}))
        return 0


def _only_arg():
    a = sys.argv[1:]
    return a[a.index("--only") + 1] if "--only" in a[:-1] else None


if __name__ == "__main__":
    sys.exit(main(only=_only_arg()))
