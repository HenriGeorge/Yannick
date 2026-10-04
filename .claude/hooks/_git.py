"""Shared git-runner (#743) — imported by the gate hooks that shell out to git.

Every gate had its own private `_run`/`_run_git` that failed SILENTLY open: on a timeout / exception /
non-zero exit it returned None (→ the gate ALLOWs) with zero trace, so a git hiccup turned the guard
into a permanent no-op nobody could see. `nocommit_guard._run_git` alone did it right. This extracts
that pattern: fail open (return None) BUT leave ONE stderr breadcrumb naming the guard, so a *blind*
allow is distinguishable from a *clean* allow. rc==0 (even empty stdout) = a genuinely clean result,
no breadcrumb.

Sibling import works because the plugin invokes hooks as `python3 .../hooks/<h>.py` (sys.path[0] is
the hooks dir). Unlike the OPTIONAL telemetry helpers (_denial_telemetry / _telemetry_gate / …, which
importers guard so a missing module degrades to no-capture), this is ESSENTIAL — a gate cannot check
git state without it — so importers do NOT guard it away; a missing module is a real, loud ImportError.
Byte-parity twin: _git.cjs.
"""
import subprocess
import sys
import time

# Hard-deadline clamp (#979): the PreToolUse entry sets a wall-clock deadline for its whole run, and
# every git subprocess here is clamped to the REMAINING budget — no single call may push the hook
# past the deadline and let the harness kill it mid-run (a kill drops the collected deny → fail-open).
# None = no deadline (the `--only` legacy path and any direct non-entry caller are unclamped).
_deadline = None  # a time.monotonic() value, or None


def set_deadline(monotonic_deadline):
    global _deadline
    _deadline = monotonic_deadline


def clear_deadline():
    global _deadline
    _deadline = None


def clamp(timeout):
    """Clamp a git-subprocess timeout to the remaining deadline budget. Floored at 0.05 s so a call
    made past the deadline times out immediately (fail-open) instead of raising on a 0/negative
    timeout. A no-op when no deadline is set."""
    if _deadline is None:
        return timeout
    return max(0.05, min(timeout, _deadline - time.monotonic()))


def run(label, cwd, argv, *, timeout=8, color_off=False, discard_output=False):
    """Run a FULL command `argv` (e.g. ["git", "rev-parse", "HEAD"] or ["gh", "pr", "list", …])
    fail-open, with a stderr breadcrumb on failure.

    label: the calling guard's name (goes in the breadcrumb). cwd: dir or None. argv: the complete
    command including argv[0] (git OR gh — several gates run both). timeout: per-caller (gates use
    5 or 8 s). color_off: insert `-c color.ui=false` right after `git` (nocommit_guard's diff scan
    needs uncolored +/- prefixes); a no-op unless argv[0] == "git".
    discard_output: send stdout/stderr to /dev/null (returns "" on rc==0) — a timed-out command whose
    own children still hold an inherited pipe can then never stall the caller (hook consolidation PR 6,
    stale_base's fetch).

    Returns stdout on rc==0 (may be ""), else None (after one breadcrumb line). The None-on-failure
    contract is identical to the private runners it replaces, so no gate's ALLOW/BLOCK path changes —
    only stderr gains a trace.
    """
    cmd = list(argv)
    if color_off and cmd[:1] == ["git"]:
        cmd = ["git", "-c", "color.ui=false", *cmd[1:]]
    shown = " ".join(argv)
    timeout = clamp(timeout)
    try:
        r = subprocess.run(cmd, cwd=cwd or None, text=True, timeout=timeout, check=False,
                           **({"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
                              if discard_output else {"capture_output": True}))
    except Exception as exc:  # noqa: BLE001 — fail open, but leave a trace
        sys.stderr.write(f"{label}: `{shown}` failed to run ({exc}); guard fail-open (did not verify)\n")
        return None
    if r.returncode != 0:
        sys.stderr.write(f"{label}: `{shown}` exited {r.returncode}; guard fail-open (did not verify)\n")
        return None
    return "" if discard_output else r.stdout
