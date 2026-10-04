#!/usr/bin/env python3
"""staged-summary.py — emit DETERMINISTIC facts about the staged diff as JSON.

This is the mechanical half of the conventional-commit skill. It does NOT choose a commit `type`
(feat/fix/…) or write a subject — that is intent inference, which stays judgment in SKILL.md. It only
reports what can be computed with certainty from `git diff --staged`, so Claude spends its tokens on the
judgment call, not on re-deriving file lists and scope candidates by hand every time.

Output (stdout, one JSON object):
  {
    "files":        ["src/api/handler.py", ...],   # staged paths
    "insertions":   <int>,                          # total added lines (numstat)
    "deletions":    <int>,                          # total removed lines (numstat)
    "scope_candidates": ["api", ...],               # component names derived from paths, ranked
    "detected_footers": ["Refs #7", "BREAKING CHANGE: ..."],  # footer hints found in ADDED lines
    "subject_length_budget": {"max": 72, "recommended": 50}
  }

Dependency-free (stdlib + git). No network, no writes. Exit 0 even when nothing is staged.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter

# Directory segments that name HOW code is organised, not WHICH component it is — never a good scope.
GENERIC_SEGMENTS = {
    "src", "lib", "app", "apps", "source", "sources", "pkg", "packages",
    "test", "tests", "__tests__", "spec", "specs", "scripts", "script",
    "dist", "build", "out", "bin", "internal", "cmd",
}

FOOTER_RE = re.compile(
    r"\b(?:Closes|Close|Fixes|Fix|Resolves|Resolve|Refs|Ref|See)\s+#\d+\b",
    re.IGNORECASE,
)
BREAKING_RE = re.compile(r"BREAKING[ -]CHANGE")


def _git(args: list[str]) -> str:
    """Run a git command, return stdout ('' on any failure — e.g. not a repo / nothing staged).

    `-c core.quotepath=false` so non-ASCII paths come back verbatim (café.py), not git's default
    octal-escaped `"caf\\303\\251.py"` form — otherwise files[]/scope_candidates would be mangled.
    """
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "-c", "color.ui=false", *args],
            capture_output=True, text=True, check=False,
        )
        return out.stdout
    except OSError:
        return ""


def scope_candidate_for(path: str) -> str | None:
    """The most-specific component directory in a path, skipping generic organising segments.

    src/api/handler.py           -> api
    global-skills/cc/scripts/x   -> cc   (scripts is generic, dropped)
    README.md                    -> None (root file, no component)
    """
    parts = path.split("/")
    dirs = parts[:-1]  # drop the filename
    if not dirs:
        return None
    meaningful = [d for d in dirs if d.lower() not in GENERIC_SEGMENTS]
    if meaningful:
        return meaningful[-1]
    # every dir was generic (e.g. tests/foo.py) — fall back to the last real dir so we still say something
    return dirs[-1]


def main() -> int:
    files = [ln for ln in _git(["diff", "--staged", "--name-only"]).splitlines() if ln.strip()]

    insertions = deletions = 0
    for row in _git(["diff", "--staged", "--numstat"]).splitlines():
        cols = row.split("\t")
        if len(cols) < 2:
            continue
        add, rem = cols[0], cols[1]
        # binary files report "-" for both — count as 0.
        insertions += int(add) if add.isdigit() else 0
        deletions += int(rem) if rem.isdigit() else 0

    ranked = Counter()
    for f in files:
        cand = scope_candidate_for(f)
        if cand:
            ranked[cand] += 1
    # most frequent first, then alphabetical for stability
    scope_candidates = [c for c, _ in sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))]

    footers: list[str] = []
    for line in _git(["diff", "--staged"]).splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        added = line[1:]
        for m in FOOTER_RE.findall(added):
            if m not in footers:
                footers.append(m)
        if BREAKING_RE.search(added) and not any(f.startswith("BREAKING") for f in footers):
            footers.append(added.strip())

    summary = {
        "files": files,
        "insertions": insertions,
        "deletions": deletions,
        "scope_candidates": scope_candidates,
        "detected_footers": footers,
        "subject_length_budget": {"max": 72, "recommended": 50},
    }
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
