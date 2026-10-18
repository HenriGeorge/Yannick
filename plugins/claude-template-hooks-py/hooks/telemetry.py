#!/usr/bin/env python3
# dependencies = []
"""PostToolUse `telemetry` — the metadata-only tool-call recorder. Matcher "" (all tools).

Module:
  tool_events — metadata-only tool row to tool-events.jsonl (no bodies/prompts/diffs)

The advisory telemetry modules (compact_suggester, loop_detector, capture_iterations,
capture_failures) were removed in the hook diet (#1285): their behaviour was inject/WARN or
self-improvement capture, not a deny-grade guard. `/improve` now corroborates recurring lessons
against `docs/lessons.md` Seen-counts plus the surviving `tool-events.jsonl`. Fail-open: always exit 0.
"""
import json
import os
import sys
import time

from _dispatch import dispatch, only_arg

try:
    from _telemetry_gate import telemetry_enabled
except Exception:  # noqa: BLE001 - degrade to enabled if the helper is missing
    def telemetry_enabled(_="."):  # type: ignore
        return True


def _tool_events(data):
    # Coerce non-dict shapes to {} (a tool may deliver tool_response/tool_input as a string) — a bare
    # .get() on a str would raise and, since this fires on EVERY call, spam a traceback (#511 review).
    resp = data.get("tool_response")
    if not isinstance(resp, dict):
        resp = {}
    exit_code = resp.get("exit")
    if exit_code is None:
        exit_code = 1 if (resp.get("error") or resp.get("is_error")) else 0
    ti = data.get("tool_input")
    if not isinstance(ti, dict):
        ti = {}
    rec = {
        "ts": int(time.time()),
        "kind": "tool",
        "tool": data.get("tool_name"),
        "exit": exit_code,
        "duration_ms": data.get("duration_ms"),
        "file": ti.get("file_path"),          # path only — never contents
        # spawn attribution (F2): the dispatched agent TYPE on an Agent/Task row (never the prompt),
        # so spawn cost is attributable by agent; null for every other tool.
        "subagent": ti.get("subagent_type") if data.get("tool_name") in ("Agent", "Task") else None,
        "retry_count": data.get("retry_count", 0),
        "session_id": data.get("session_id"),
    }
    try:
        proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        if not telemetry_enabled(proj):
            return None
        out_dir = os.path.join(proj, ".claude", "telemetry")
        os.makedirs(out_dir, exist_ok=True)  # inside the guard — an unwritable path must not traceback
        with open(os.path.join(out_dir, "tool-events.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:  # noqa: BLE001 - best-effort; leave a breadcrumb, never brick the tool
        print(f"tool_events: telemetry write failed: {e}", file=sys.stderr)
    return None


MODULES = (
    ("tool_events", _tool_events),
)


def main(only=None) -> int:
    return dispatch("telemetry", MODULES, only)


if __name__ == "__main__":
    sys.exit(main(only=only_arg()))
