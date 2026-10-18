#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Static trigger-quality lint over skill descriptions (a SKILL.md's frontmatter `description:`).

Heuristics from the writing-skills SDO — borrowed from okjpg/skill-audit, reimplemented
native/zero-dep (no live GPT/Gemini calls). Flags, never scores. Exit 0 always; fails open.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DESC_BUDGET = 500
WORKFLOW_LEAK = re.compile(r"\bstep 1\b|(?:^|\s)[12]\.\s", re.IGNORECASE)


def _description(text):
    # minimal frontmatter description extractor (stdlib only — no yaml dep).
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    for line in text[3:end].splitlines():
        if line.strip().lower().startswith("description:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return None


def _name(path, text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if line.strip().lower().startswith("name:"):
                    return line.split(":", 1)[1].strip().strip("'\"")
    return path.parent.name


def _row(severity, summary):
    return {
        "axis": "skills",
        "severity": severity,
        "summary": summary,
        "blast_radius": "repo",
        "runtime_corroborated": False,
        "executor": "improve-skills",
    }


def _scan(root):
    findings = []
    base = Path(root)
    if not base.exists():
        return findings
    for skill_md in sorted(base.rglob("SKILL.md")):
        if "plugins" in skill_md.relative_to(base).parts:
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # fail open on an unreadable file
        desc = _description(text)
        if desc is None:
            continue
        name = _name(skill_md, text)
        if not desc.lower().startswith("use when"):
            findings.append(_row("medium", f"{name}: description should start with 'Use when…' (trigger clarity)"))
        if len(desc) > DESC_BUDGET:
            findings.append(_row("low", f"{name}: description is {len(desc)} chars (over {DESC_BUDGET}-char budget)"))
        if WORKFLOW_LEAK.search(desc):
            findings.append(_row("low", f"{name}: description leaks a workflow summary"))
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    findings = _scan(args.root)
    if args.json:
        print(json.dumps(findings))
    else:
        if not findings:
            print("skills: all descriptions trigger-clean.")
        for f in findings:
            print(f"[{f['severity']}] {f['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
