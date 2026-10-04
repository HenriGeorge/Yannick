#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""model-routing-audit scan — STATIC bare-alias leak scanner (design finding C3).

Scans a target tree for the two STATICALLY-detectable bare-alias leak surfaces:
  1. a `model:` assignment in a file's LEADING frontmatter block (agent/skill definitions) whose
     value is a bare floating alias (`sonnet`/`opus`/`haiku`/`fable` — floats to the newest
     generation);
  2. a `--model <value>` flag (shell / scripts / commands), value optionally quoted, one of the same.

Policy is to pin an EXACT model ID; a bare alias is the leak. An exact pinned ID of ANY generation
(`claude-opus-4-8`, `claude-haiku-4-5-20251001`, `claude-opus-5-5`, `claude-sonnet-5`) is clean.

It is precise on PURPOSE: it inspects only a leading-frontmatter `model:` and a real `--model` flag,
never prose — so a doc that merely mentions the alias words is not a false positive. Known limitation:
a `model:` OUTSIDE the leading frontmatter (a nested YAML key, a `"model"` in settings.json) is
deliberately NOT scanned — see SKILL.md.

BOUNDARY (design C3): the runtime Agent/Task-tool `model:` PARAMETER is NOT a static string in any
file — this scanner CANNOT see it. That surface is covered at runtime by hook H11 (Agent/Task
model-guard, hooks/pre_tool_use.py, #179), NOT by this skill. A clean scan here does NOT prove the
runtime param is safe — that's H11's job (and only where the hook is registered).

Reuses the grep patterns pinned by `tests/test_model_routing.sh` (MR-01/MR-02) so the two never drift.

Usage: scan.py [--root DIR] [--json]
Exit 1 if any leak is found (usable as a gate), 0 if clean, 2 on a usage error.
"""
import argparse
import json
import re
import sys
from pathlib import Path

BARE_ALIASES = {"sonnet", "opus", "haiku", "fable"}

MODEL_ASSIGN_RE = re.compile(r"^\s*model:\s*(?P<val>\S+)")            # a `model:` line
# --model <value>, value optionally quoted. The value must START with an alnum so a shell expansion
# (--model "${VAR}") or a printf placeholder (--model %s) doesn't match — only a literal model token.
MODEL_FLAG_RE = re.compile(r"--model[=\s]+[\"']?(?P<val>[A-Za-z0-9][A-Za-z0-9._-]*)")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<fm>.*?\n)---\s*\n?", re.S)

# Read these to inspect leading frontmatter for a `model:` leak.
SCAN_EXTS = {
    ".md", ".markdown", ".sh", ".bash", ".py", ".js", ".mjs", ".cjs",
    ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml",
}
# Scan ONLY these for a `--model` flag — a real invocation lives in a script, not in prose. This is
# what keeps a doc/table that merely mentions such a flag as an example from being a false positive.
FLAG_EXTS = {".sh", ".bash", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx"}
SKIP_DIRS = {".git", "node_modules", "plugins", ".next", "dist", "build", "__pycache__", ".venv"}


def bad_value(raw: str) -> str | None:
    """Return a leak-kind label if `raw` is a bare alias, else None."""
    val = raw.strip().strip("\"'")
    if val in BARE_ALIASES:
        return "bare-alias"
    return None


def scan_file(path: Path, text: str, rel: str) -> list[dict]:
    findings: list[dict] = []

    # (1) `model:` leak — ONLY inside the leading frontmatter block. A `model:` written in body prose
    #     or a printf/heredoc that emits example config is NOT a real routing decision, so scoping to
    #     the actual frontmatter block is what makes this precise on docs and tests.
    fm = FRONTMATTER_RE.match(text)
    if fm:
        for i, line in enumerate(fm.group("fm").splitlines(), start=2):  # line 1 is the opening ---
            m = MODEL_ASSIGN_RE.match(line)
            if m:
                kind = bad_value(m.group("val"))
                if kind:
                    findings.append({"file": rel, "line": i,
                                     "kind": f"{kind}:model-assignment", "value": m.group("val").strip()})

    # (2) `--model` flag — ONLY in script files (a real command invocation).
    if path.suffix.lower() in FLAG_EXTS:
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in MODEL_FLAG_RE.finditer(line):
                kind = bad_value(m.group("val"))
                if kind:
                    findings.append({"file": rel, "line": lineno,
                                     "kind": f"{kind}:model-flag", "value": m.group("val").strip()})
    return findings


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(seg in SKIP_DIRS for seg in p.relative_to(root).parts):
            continue
        if p.suffix.lower() not in SCAN_EXTS:
            continue
        yield p


def scan(root: Path) -> list[dict]:
    findings: list[dict] = []
    for f in iter_files(root):
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_file(f, text, str(f.relative_to(root))))
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="directory to scan (default: current dir)")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2

    findings = scan(root)

    if args.json:
        print(json.dumps(findings, indent=2))
    elif findings:
        print(f"Bare-alias leak surfaces found ({len(findings)}):")
        for x in findings:
            print(f"  {x['file']}:{x['line']}: [{x['kind']}] {x['value']}")
        print("\nStatic surfaces only — the runtime Agent-tool `model:` param is covered at runtime "
              "by hook H11 (Agent/Task model-guard), not here; see SKILL.md.")
    else:
        print("No static bare-alias leak surfaces found.")
        print("NOTE: the runtime Agent/Task-tool `model:` param is covered by hook H11, not here "
              "(see SKILL.md).")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
