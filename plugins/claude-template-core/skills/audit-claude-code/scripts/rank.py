#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Rank a JSON array of common-shape audit findings by severity x runtime-corroboration x blast-radius.

Deterministic: ties break by (axis, summary) ascending. Exit 0 always; fails open on bad input.
"""
import argparse
import json
import sys

SEV_W = {"high": 3, "medium": 2, "low": 1}


def _score(f):
    sev = SEV_W.get(f.get("severity"), 1)
    rt = 2 if f.get("runtime_corroborated") else 1
    br = 2 if f.get("blast_radius") == "template" else 1
    return sev * rt * br


def _load(args):
    try:
        raw = open(args.findings, encoding="utf-8").read() if args.findings else sys.stdin.read()
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (OSError, ValueError, TypeError):
        return []  # fail open


def _rank(findings):
    scored = [dict(f, score=_score(f)) for f in findings if isinstance(f, dict)]
    scored.sort(key=lambda f: (-f["score"], f.get("axis", ""), f.get("summary", "")))
    for i, f in enumerate(scored, 1):
        f["rank"] = i
    return scored


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    ranked = _rank(_load(args))
    if args.json:
        print(json.dumps(ranked))
    else:
        if not ranked:
            print("no findings.")
        for f in ranked:
            print(f"{f['rank']:>3} | {f.get('axis','?'):<8} | {f.get('severity','?'):<6} | "
                  f"{f.get('summary','')} -> {f.get('executor','none')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
