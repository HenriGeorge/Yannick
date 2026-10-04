#!/usr/bin/env python3
# dependencies = []
"""TeammateIdle hook — keep an in-process crew teammate working while it still owns tasks.

When a teammate goes idle with pending tasks, exit 2 (the event's keep-working signal) with a nudge;
with nothing pending, allow the idle. Fail-open (exit 0) on malformed input.
"""
import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("hook_event_name") != "TeammateIdle":
        return 0
    pending = payload.get("pending_tasks")
    try:
        pending = int(pending)
    except (TypeError, ValueError):
        return 0
    if pending > 0:
        name = payload.get("teammate_name") or "teammate"
        print(f"{name}: {pending} task(s) still pending — pick up the next one before idling "
              "(TaskList → claim → work).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
