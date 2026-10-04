#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Mine .claude/telemetry/tool-events.jsonl for repeated runtime failures.

Emits common-shape findings (see the audit-claude-code plan Global Constraints).
Conservative: flags REPEATED failure/thrash/latency, never one-offs. Exit 0 always;
fails open on missing/malformed input.
"""
import argparse
import json
import sys
from collections import defaultdict

FAIL_MIN = 3        # need >=3 failures before flagging
FAIL_RATE = 0.20    # and >=20% failure rate
THRASH_MIN = 2      # >=2 retried(>=2) calls
LAT_FLOOR_MS = 5000 # absolute latency floor to kill noise
LOOP_MIN = 2        # >=2 loop_detector rows on one file


def _load(path, window):
    """Return (tool_rows[last window], loop_rows[all]); fail open on a missing/bad file/line."""
    tool_rows, loop_rows = [], []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (ValueError, TypeError):
                    continue  # fail open on a bad line
                if not isinstance(rec, dict):
                    continue
                if rec.get("kind") == "tool" and rec.get("tool"):
                    tool_rows.append(rec)
                elif rec.get("kind") == "loop" and rec.get("file"):
                    loop_rows.append(rec)
    except OSError:
        return [], []  # fail open on a missing/unreadable file
    return (tool_rows[-window:] if window else tool_rows), loop_rows


def _percentile(values, pct):
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


def _find(rows, loop_rows):
    findings = []
    by_tool = defaultdict(list)
    for r in rows:
        by_tool[r["tool"]].append(r)

    # failure-rate
    for tool, rs in sorted(by_tool.items()):
        total = len(rs)
        fails = sum(1 for r in rs if (r.get("exit") or 0) != 0)
        rate = fails / total if total else 0.0
        if fails >= FAIL_MIN and rate >= FAIL_RATE:
            findings.append(_row(
                "high" if rate >= 0.5 else "medium",
                f"{tool}: {fails}/{total} calls failed ({round(rate*100)}%)"))

    # thrash
    for tool, rs in sorted(by_tool.items()):
        thr = sum(1 for r in rs if (r.get("retry_count") or 0) >= 2)
        if thr >= THRASH_MIN:
            findings.append(_row("medium", f"{tool}: {thr} calls retried >=2x (thrash)"))

    # latency outliers
    durs = [r["duration_ms"] for r in rows if isinstance(r.get("duration_ms"), (int, float))]
    p90 = _percentile(durs, 90)
    if p90 is not None:
        for tool, rs in sorted(by_tool.items()):
            tdurs = [r["duration_ms"] for r in rs if isinstance(r.get("duration_ms"), (int, float))]
            if not tdurs:
                continue
            mx = max(tdurs)
            if mx >= p90 and mx >= LAT_FLOOR_MS:
                findings.append(_row("low", f"{tool}: slow call {mx}ms (p90 outlier)"))

    # loop hotspot (uses the loop_detector rows we already collect)
    by_file = defaultdict(int)
    for r in loop_rows:
        by_file[r["file"]] += 1
    for f, n in sorted(by_file.items()):
        if n >= LOOP_MIN:
            findings.append(_row("medium", f"loop hotspot: {f} ({n} loops)"))
    return findings


def _row(severity, summary):
    return {
        "axis": "runtime",
        "severity": severity,
        "summary": summary,
        "blast_radius": "repo",
        "runtime_corroborated": True,
        "executor": "none",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--window", type=int, default=200)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tool_rows, loop_rows = _load(args.events, args.window)
    findings = _find(tool_rows, loop_rows)

    if args.json:
        print(json.dumps(findings))
    else:
        if not findings:
            print("runtime: no repeated failures found.")
        for f in findings:
            print(f"[{f['severity']}] {f['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
