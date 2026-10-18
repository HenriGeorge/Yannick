"""Shared fail-open visibility helper (#960/#953).

An exit-0 hook's stderr is NEVER shown to the agent, so a fail-open breadcrumb written to stderr is
invisible — a degraded guard then looks identical to a clean one. The single sanctioned way to
surface a fail-open on an exit-0 hook is ONE stdout `{"systemMessage": …}` object. These two helpers
are that single emitter + its breadcrumb formatter, so every fail-open path speaks with one voice.

Dependency-free (stdlib json only) so every hook — PostToolUse, PreCompact, SessionStart — can import
it without pulling in the PreToolUse decision plumbing. Byte-parity twin: _lib/notice.cjs.
"""
import json


def fail_open_notice(msg):
    """Emit ONE stdout `{"systemMessage": msg}` (visible on an exit-0 hook, where stderr is not).

    Callers that aggregate several notes join them FIRST and pass one string — a hook process must
    print at most one JSON object (the harness reads the first)."""
    print(json.dumps({"systemMessage": msg}))  # noqa: T201


def skipped_notice(entry, module, exc):
    """The breadcrumb text for a fail-open module skip: `<entry>: <module> skipped (<exc>)`. Shared
    by _dispatch (a module that propagated) and the module catch-alls (a module that caught its own
    unexpected error) so both read identically wherever they surface."""
    return f"{entry}: {module} skipped ({exc})"
