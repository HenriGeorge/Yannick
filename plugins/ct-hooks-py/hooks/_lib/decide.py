"""Shared PreToolUse decision plumbing (hook consolidation PR 5): the deny emitter and the fail-open
guard runner. Guards never exit — they return a reason; the entry decides (first DENY wins).
Denial telemetry was removed in the hook diet (#1285)."""
import json
import sys

from _lib.shell import _chained_ops_warning


def run(fn, ctx, off, module):
    """Run one guard fail-OPEN: a bug is logged and skipped, never a crash (spec § Error handling).
    The guard's module is recorded in `off` so the entry can tell the user it was OFF."""
    try:
        return fn(ctx)
    except Exception as exc:  # noqa: BLE001 - fail open, never brick a session
        sys.stderr.write(f"[pre_tool_use] guard {module} fail-opened: {exc!r}\n")
        off.append(module)
        return None


def off_message(off):
    """The user-visible notice for guards that were OFF this call (stderr is never shown on exit 0)."""
    names = ", ".join(dict.fromkeys(off))
    return (f"pre_tool_use: guard(s) OFF this call — {names} failed to load or crashed; "
            "run setup.sh --update-hooks")


def _deny_sysmsg(off, notes):
    """The combined systemMessage for a DENY: the OFF-guard notice + any fail-open breadcrumbs the
    entry collected (git-read failures, skipped checks). None when there's nothing to add — so a
    plain deny stays byte-identical to the pre-#979 form."""
    parts = []
    if off:
        parts.append(off_message(off))
    if notes:
        parts.append("\n".join(notes))
    return "\n".join(parts) if parts else None


def deny(reason, command="", off=(), notes=()):
    """Today's block JSON (+ the #574 chained-ops note for a Bash command), exit 2. The OFF notice
    and any fail-open breadcrumbs (#979/M1) ride along as a systemMessage in the SAME JSON object."""
    out = {"decision": "block", "reason": reason + _chained_ops_warning(command)}
    msg = _deny_sysmsg(off, notes)
    if msg is not None:
        out["systemMessage"] = msg
        # On exit 2 Claude Code reads stderr, not stdout JSON — the notice must ride there too.
        sys.stderr.write(msg + "\n")
    print(json.dumps(out))  # noqa: T201
    sys.exit(2)


def block_dual(reason, off=(), notes=()):
    """The commit gates' deny form — legacy top-level decision + hookSpecificOutput deny, the reason
    on stderr, exit 2. pre_tool's joined deny uses it too. The OFF notice and any fail-open
    breadcrumbs (#979/M1) ride along as a systemMessage in the SAME JSON object (stdout-visible)."""
    out = {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
    }
    msg = _deny_sysmsg(off, notes)
    if msg is not None:
        out["systemMessage"] = msg
        sys.stderr.write(msg + "\n")
    print(json.dumps(out))  # noqa: T201
    print(reason, file=sys.stderr)  # noqa: T201
    sys.exit(2)


def deny_json(reason):
    """test_lock_enforce's legacy deny form (`--only test_lock_enforce` only): JSON deny, exit 0."""
    print(json.dumps({  # noqa: T201
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, indent=1))
