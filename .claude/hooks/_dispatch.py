#!/usr/bin/env python3
# dependencies = []
"""Shared entry loop for the consolidated hooks (hook consolidation PR 4).

Reads stdin ONCE, runs each module in order (or only `only`), and prints at most ONE
{"systemMessage": …} — several messages are joined with "\\n" (one hook process = one JSON object).
A module that raises is skipped with a stderr breadcrumb; the rest still run. Always returns 0.

Bad stdin reproduces the retired hooks exactly: by default empty / non-JSON / non-object stdin runs
nothing (every retired PostToolUse module produced nothing there). An entry whose retired hooks DID
act on empty stdin passes empty_ok=True: empty stdin then runs every module with data={} (the old
`json.loads(stdin or "{}")`), e.g. stop_record's stop_log still logs the stop.
"""
import json
import sys

from _lib.notice import fail_open_notice, skipped_notice


def dispatch(entry, modules, only=None, empty_ok=False) -> int:
    if only and only not in {name for name, _ in modules}:
        print(f"{entry}: unknown module {only}", file=sys.stderr)  # noqa: T201
        return 0
    try:
        raw = sys.stdin.read()
    except Exception as e:  # noqa: BLE001 — align with the node twin: never crash on a stdin read
        print(f"{entry}: stdin read failed ({e})", file=sys.stderr)  # noqa: T201
        raw = ""
    if not raw.strip():
        if not empty_ok:
            return 0
        raw = "{}"
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    msgs = []
    for name, fn in modules:
        if only and name != only:
            continue
        try:
            msg = fn(data)
        except Exception as e:  # noqa: BLE001 - one module's crash must never skip the others
            # #953/#960: surface the skip on STDOUT (an exit-0 hook never shows stderr), not just here.
            crumb = skipped_notice(entry, name, e)
            print(crumb, file=sys.stderr)  # noqa: T201
            msgs.append(crumb)
            continue
        if msg:
            msgs.append(msg)
    if msgs:
        fail_open_notice("\n".join(msgs))
    return 0
