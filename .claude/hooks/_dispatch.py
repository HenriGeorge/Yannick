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


def dispatch(entry, modules, only=None, empty_ok=False) -> int:
    if only and only not in {name for name, _ in modules}:
        print(f"{entry}: unknown module {only}", file=sys.stderr)
        return 0
    raw = sys.stdin.read()
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
            print(f"{entry}: {name} skipped ({e})", file=sys.stderr)
            continue
        if msg:
            msgs.append(msg)
    if msgs:
        print(json.dumps({"systemMessage": "\n".join(msgs)}))
    return 0
