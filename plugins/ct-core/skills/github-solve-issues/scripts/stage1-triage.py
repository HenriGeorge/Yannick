#!/usr/bin/env python3
"""stage1-triage.py — the deterministic core of github-solve-issues Stage 1.

Mechanical loop only: ensure category labels exist → fetch open issues → batch them through a
classifier command → parse → apply one `category:*` label per issue → a BOUNDED coverage-gate loop
that re-classifies stragglers (issues still missing a category label) at most twice, then FAILS LOUD
rather than looping forever. Judgment stays in SKILL.md: escalating stubborn stragglers to Claude
Code, human review of low-confidence rows, the category scheme itself.

Externalised (so this stays testable and cheap):
  - `gh` CLI on PATH does every GitHub read/write (list, label create, issue edit).
  - The classifier is a command, default the pinned-Haiku `claude -p` path, overridable via
    TRIAGE_CLASSIFY_CMD (shlex-split; the prompt is appended as the final argument).

Exit codes: 0 = every open issue labeled; 3 = coverage gate exhausted its bounded retries with
stragglers remaining (their numbers are printed). Dependency-free (stdlib + gh).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

CATEGORIES = ["mechanical", "bug", "design-decision", "docs", "chore", "question"]
# Distinct label colours per category (GitHub hex, no '#') so the triage taxonomy is
# scannable at a glance instead of a wall of default grey (`ededed`). Any category absent
# here falls back to grey.
CATEGORY_COLORS = {
    "bug": "d93f0b",             # orange-red
    "mechanical": "006b75",      # teal
    "design-decision": "6f42c1", # purple
    "docs": "0075ca",            # blue
    "chore": "fbca04",           # amber
    "question": "cc317c",        # pink
}
# Two best-effort prioritization dimensions applied ALONGSIDE category — impact (how much it matters)
# and effort (how big the change is). "Most effective" = high impact + small effort. Unlike category,
# a missing/invalid value is skipped (never a coverage-gate straggler); category stays load-bearing.
IMPACTS = ["high", "med", "low"]
EFFORTS = ["S", "M", "L"]
IMPACT_COLORS = {"high": "b60205", "med": "d93f0b", "low": "fef2c0"}  # red / orange-red / pale-amber
EFFORT_COLORS = {"S": "0e8a16", "M": "fbca04", "L": "5319e7"}         # green / amber / purple

# Flag labels raised by the two GATE-0/dedup detectors — human-review only, NEVER auto-close.
TRIAGE_SOLVED = "triage:likely-solved"
TRIAGE_DUP = "triage:likely-dup"
MAX_STRAGGLER_ITERS = 2  # hard bound — the grill gotcha was an unbounded coverage loop
BODY_CAP = 1500

# Default classifier: the pinned cheap-Claude path (Haiku 4.5), NEVER a bare `haiku` alias (it floats
# to the newest generation) and NEVER `claude --bare` (refuses OAuth). Overridable via TRIAGE_CLASSIFY_CMD for tests.
DEFAULT_CLASSIFY_CMD = [
    "claude", "-p", "--strict-mcp-config", "--model", "claude-haiku-4-5-20251001",
]

PROMPT_PATH = Path(__file__).resolve().parent.parent / "classify-prompt.md"


def gh(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def ensure_labels(dry_run: bool) -> None:
    """Create each category:* label. Idempotent — a non-zero exit ('already exists') is ignored."""
    if dry_run:
        return
    for c in CATEGORIES:
        color = CATEGORY_COLORS.get(c, "ededed")
        gh(["label", "create", f"category:{c}", "--color", color,
            "--description", f"triage: {c}"], check=False)  # tolerate "already exists"
        # Recolour a label that pre-existed grey — `create` no-ops once it exists, so a
        # repo triaged before this map shipped keeps its grey `ededed` without this edit.
        gh(["label", "edit", f"category:{c}", "--color", color], check=False)
    # Prioritization labels: impact:* and effort:* (same idempotent create+recolour as category).
    for v in IMPACTS:
        gh(["label", "create", f"impact:{v}", "--color", IMPACT_COLORS.get(v, "ededed"),
            "--description", f"triage: {v} impact"], check=False)
        gh(["label", "edit", f"impact:{v}", "--color", IMPACT_COLORS.get(v, "ededed")], check=False)
    for v in EFFORTS:
        gh(["label", "create", f"effort:{v}", "--color", EFFORT_COLORS.get(v, "ededed"),
            "--description", f"triage: {v} effort"], check=False)
        gh(["label", "edit", f"effort:{v}", "--color", EFFORT_COLORS.get(v, "ededed")], check=False)
    # The two detector flag labels (grill S3 — must exist before a detector edits with them).
    for name, desc in ((TRIAGE_SOLVED, "flag: likely already solved on the default branch"),
                       (TRIAGE_DUP, "flag: likely duplicate of another open issue")):
        gh(["label", "create", name, "--color", "d4c5f9",
            "--description", desc], check=False)  # tolerate "already exists"


def die(msg: str) -> "NoReturn":  # noqa: F821
    print(msg, file=sys.stderr)
    sys.exit(2)


def fetch_issues() -> list[dict]:
    r = gh(["issue", "list", "--state", "open", "--limit", "200",
            "--json", "number,title,body"])
    # Gate on gh's exit code FIRST — an empty [] fallback on a failed query would falsely read as
    # "no open issues" and let the run exit 0 (silent failure). A real failure must be loud.
    if r.returncode != 0:
        die(f"`gh issue list` failed (exit {r.returncode}): {r.stderr.strip()}")
    try:
        return json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        die(f"`gh issue list` returned unparseable JSON: {r.stdout[:200]!r}")


def default_branch() -> str:
    """The repo's default branch — the grill-C1 condition for 'solved on main'."""
    r = gh(["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"])
    if r.returncode != 0:
        die(f"`gh repo view` (default branch) failed (exit {r.returncode}): {r.stderr.strip()}")
    name = (r.stdout or "").strip()
    if not name:
        die("could not determine the repository default branch")
    return name


def _closing_prs(number: int) -> list[int]:
    """PR numbers linked to issue #number by a CLOSING keyword (gh's own link graph)."""
    r = gh(["issue", "view", str(number), "--json", "closedByPullRequestsReferences"])
    if r.returncode != 0:
        return []  # read-only probe: a miss is "no signal", never a false flag
    try:
        obj = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return []
    if not isinstance(obj, dict):  # grill C1: defensive — a stray array (or a fixture) → no signal
        return []
    refs = obj.get("closedByPullRequestsReferences") or []
    return [p["number"] for p in refs if isinstance(p, dict) and isinstance(p.get("number"), int)]


def _pr_merged_to(pr: int, default: str) -> bool:
    """True iff PR #pr is MERGED into the default branch (grill C1 — not merely 'merged')."""
    r = gh(["pr", "view", str(pr), "--json", "state,baseRefName,mergedAt"])
    if r.returncode != 0:
        return False
    try:
        d = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return False
    if not isinstance(d, dict):
        return False
    return d.get("state") == "MERGED" and d.get("baseRefName") == default and bool(d.get("mergedAt"))


def detect_solved(issues: list[dict], dry_run: bool) -> dict[int, int]:
    """Flag each open issue closed by a merged PR on the DEFAULT branch (grill C1). gh-only — makes
    ZERO classifier calls. default_branch() is resolved LAZILY (grill S3): a candidate-free run never
    touches `gh repo view`, so it never die()s on a dry-run preview. Returns {issue: closing_pr}."""
    solved: dict[int, int] = {}
    default: "str | None" = None
    for issue in issues:
        num = issue["number"]
        prs = _closing_prs(num)
        if not prs:
            continue
        if default is None:
            default = default_branch()  # lazy — only once a real candidate exists
        for pr in prs:
            if _pr_merged_to(pr, default):
                solved[num] = pr
                if not dry_run:
                    gh(["issue", "edit", str(num), "--add-label", TRIAGE_SOLVED], check=False)
                break
    return solved


def batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def extract_json_array(text: str):
    """Parse the first `[`…last `]` slice as JSON. Returns the list, or None if it won't parse."""
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, list) else None
    except json.JSONDecodeError:
        return None


def classify_batch(batch: list[dict], classify_cmd: list[str]) -> list[dict]:
    """Classify one batch; re-run ONCE if the first output doesn't parse. [] if both attempts fail."""
    slim = [{"number": i["number"], "title": i.get("title", ""),
             "body": (i.get("body", "") or "")[:BODY_CAP]} for i in batch]
    prompt = PROMPT_PATH.read_text() + "\n" + json.dumps(slim)
    for attempt in range(2):  # original + one retry (bounded)
        proc = subprocess.run([*classify_cmd, prompt], capture_output=True, text=True, check=False)
        parsed = extract_json_array(proc.stdout)
        if parsed is not None:
            return parsed
    return []


def classify_and_apply(issues: list[dict], classify_cmd: list[str], batch_size: int,
                       dry_run: bool) -> "tuple[dict[int, dict], dict[int, list[int]]]":
    """Classify + label. Returns (results, dups) where dups maps an issue → its likely-dup group
    (Detector 2 — piggybacks the classifier's additive `dup_of` field; grill S2: purely additive)."""
    results: dict[int, dict] = {}
    dups: dict[int, list[int]] = {}
    for batch in batched(issues, batch_size):
        for row in classify_batch(batch, classify_cmd):
            num = row.get("number")
            cat = row.get("category")
            if num is None or cat not in CATEGORIES:
                continue
            results[num] = row
            dup_of = row.get("dup_of")
            if isinstance(dup_of, list):
                group = sorted({num, *(d for d in dup_of if isinstance(d, int))})
                if len(group) > 1:
                    dups[num] = group
                    if not dry_run:
                        gh(["issue", "edit", str(num), "--add-label", TRIAGE_DUP], check=False)
            if not dry_run:
                gh(["issue", "edit", str(num), "--add-label", f"category:{cat}"], check=False)
                # Additive prioritization labels: validated, best-effort — an absent/invalid value is
                # skipped (NOT a coverage-gate straggler; category above is the gated one). Unlike
                # category, a failed apply has no coverage backstop, so log a breadcrumb rather than
                # drop it silently (verify-workflow: surface the failure even when you continue).
                for field, valid in (("impact", IMPACTS), ("effort", EFFORTS)):
                    val = row.get(field)
                    if val not in valid:
                        continue
                    r = gh(["issue", "edit", str(num), "--add-label", f"{field}:{val}"], check=False)
                    if r.returncode != 0:
                        print(f"warn: {field}:{val} not applied to #{num}: {r.stderr.strip()}",
                              file=sys.stderr)
    return results, dups


def stragglers() -> list[int]:
    """Open issues still carrying NO category:* label (the coverage-gate query)."""
    r = gh(["issue", "list", "--state", "open", "--limit", "200",
            "--json", "number,labels", "--jq",
            '[.[] | select((.labels|map(.name)|any(startswith("category:")))|not) | .number]'])
    # Same guard: a failed coverage query must not silently read as "no stragglers" (false all-clear).
    if r.returncode != 0:
        die(f"`gh issue list` (coverage gate) failed (exit {r.returncode}): {r.stderr.strip()}")
    try:
        nums = json.loads(r.stdout or "[]")
        return [int(n) for n in nums]
    except (json.JSONDecodeError, ValueError, TypeError):
        die(f"coverage-gate query returned unparseable output: {r.stdout[:200]!r}")


def print_table(issues: list[dict], results: dict[int, dict],
                solved: dict[int, int], dups: dict[int, list[int]]) -> None:
    by_num = {i["number"]: i for i in issues}
    print("| # | title | category | impact | effort | confidence | reason | solved-by | dups |")
    print("|---|---|---|---|---|---|---|---|---|")
    for num in sorted(by_num):
        r = results.get(num, {})
        title = (by_num[num].get("title", "") or "").replace("|", "/")[:60]
        conf = r.get("confidence", "")
        flag = " ⚠" if isinstance(conf, (int, float)) and conf < 0.6 else ""
        imp = r.get("impact") if r.get("impact") in IMPACTS else ""
        eff = r.get("effort") if r.get("effort") in EFFORTS else ""
        sb = f"#{solved[num]}" if num in solved else ""
        dg = ",".join(str(x) for x in dups[num]) if num in dups else ""
        print(f"| {num} | {title} | {r.get('category', '—')}{flag} | {imp} | {eff} | {conf} | "
              f"{(r.get('reason', '') or '').replace('|', '/')} | {sb} | {dg} |")
    if solved:
        # W2: a DEFAULT exclusion, not a lock — an explicit `N` argument still solves these.
        print(f"\nExcluded from default solve set (already solved on the default branch; flag only, "
              f"explicit N still solves): {sorted(solved)}")
    if dups:
        print(f"Likely-duplicate groups (human reviews before solving): "
              f"{[dups[n] for n in sorted(dups)]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage-1 issue triage (label every open issue).")
    ap.add_argument("--dry-run", action="store_true",
                    help="classify + report only; create no labels, edit no issues")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--json", action="store_true", help="also emit the triage rows as JSON")
    args = ap.parse_args()

    env_cmd = os.environ.get("TRIAGE_CLASSIFY_CMD")
    classify_cmd = shlex.split(env_cmd) if env_cmd else DEFAULT_CLASSIFY_CMD

    ensure_labels(args.dry_run)
    issues = fetch_issues()
    if not issues:
        print("No open issues to triage.")
        return 0

    results, dups = classify_and_apply(issues, classify_cmd, args.batch_size, args.dry_run)

    if not args.dry_run:
        # BOUNDED coverage gate: re-classify stragglers at most MAX_STRAGGLER_ITERS times.
        left = stragglers()
        it = 0
        while left and it < MAX_STRAGGLER_ITERS:
            it += 1
            straggler_issues = [i for i in issues if i["number"] in set(left)]
            r2, d2 = classify_and_apply(straggler_issues, classify_cmd, args.batch_size,
                                        dry_run=False)
            results.update(r2)
            dups.update(d2)
            left = stragglers()
        if left:
            print_table(issues, results, {}, dups)
            print(f"\nCOVERAGE GATE FAILED after {MAX_STRAGGLER_ITERS} straggler iteration(s): "
                  f"{len(left)} issue(s) still unlabeled: {sorted(left)}", file=sys.stderr)
            print("Escalate these stragglers to a Claude Code classification (see SKILL.md).",
                  file=sys.stderr)
            return 3

    # Detector 1 — solved-on-main (gh-only, mechanical). A flag never changes the exit code (GS-8).
    solved = detect_solved(issues, args.dry_run)

    print_table(issues, results, solved, dups)
    if args.json:
        rows = []
        for n in sorted(results):
            row = dict(results[n])
            row["likely_solved"] = n in solved
            row["solved_by"] = solved.get(n)
            row["dup_of"] = row.get("dup_of") or []  # grill S1: keep the classifier's own dup_of
            rows.append(row)
        print("\n" + json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
