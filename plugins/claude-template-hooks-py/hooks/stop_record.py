#!/usr/bin/env python3
# dependencies = []
"""Stop `stop_record` — the Stop-time recorder (hook consolidation PR 4; trimmed in the hook diet, #1285).

Modules:
  stop_log — session summary row to .claude/session-logs/<date>.jsonl (30-day retention)

(cost_telemetry and improvement_proposer were removed in the hook diet — cost telemetry duplicated
what the transcript already holds, and the proposal stub was superseded by the on-demand /improve
command.)

Empty stdin still runs every module with {} (the retired hooks parsed `stdin or "{}"`), so the stop
is logged; non-JSON stdin runs nothing, as before. Never blocks the stop. Each module keeps its sink,
format and breadcrumb byte for byte (golden: tests/test_hook_golden.sh). The retired stop_log.py file
forwards here with main(only="stop_log").
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from _dispatch import dispatch, only_arg


# ---- stop_log -------------------------------------------------------------------------------------
def _stop_log(data):
    session_id = data.get("session_id", "unknown")
    stop_reason = data.get("stop_reason", "unknown")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_entry = {
        "timestamp": timestamp,
        "session_id": session_id,
        "stop_reason": stop_reason,
    }
    date_str = datetime.now().strftime("%Y-%m-%d")

    try:
        # Root at the project dir, not the CWD — a session whose cwd is elsewhere (e.g. inside a
        # docs/ subfolder) must not drop a stray .claude/session-logs/ there. Mirrors the Node twin.
        proj = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        log_dir = Path(proj) / ".claude" / "session-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{date_str}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
        # Keep only last 30 days
        logs = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        for old in logs[:-30]:
            old.unlink()
    except OSError as e:
        # best-effort logging (never crash the Stop hook) — but leave a breadcrumb so a missing
        # log trail is diagnosable rather than silent.
        print(f"stop_log: could not write session log: {e}", file=sys.stderr)
    return None


MODULES = (
    ("stop_log", _stop_log),
)


def main(only=None) -> int:
    # empty_ok: the retired Stop hooks parsed `stdin or "{}"`, so an empty payload still logged the stop.
    return dispatch("stop_record", MODULES, only, empty_ok=True)


if __name__ == "__main__":
    sys.exit(main(only=only_arg()))
