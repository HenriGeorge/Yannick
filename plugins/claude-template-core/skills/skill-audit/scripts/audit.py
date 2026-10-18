#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""skill-audit scan — deterministic half of the `/skill-audit` skill (issue #154).

Scans `**/SKILL.md` under a root directory and emits one proposal ROW per skill: recommended
min-viable `model:`, `context: fork` candidacy, deterministic-steps-should-be-a-script candidacy,
missing `## Gotchas`, missing an explicit pass/fail verdict step, and a portability warning for any
row that would introduce a Claude-Code-only frontmatter field (`model:`/`context:`/`effort:`/
`agent:`/`background:`/`hooks:`/`paths:`) onto a skill not already committed to being
Claude-Code-only — the Agent-Skills spec (claude.ai upload / Skills API / `package_skill.py`) allows
only a fixed 6-field frontmatter and hard-fails on extras (rules/agent-delegation.md, issue #154
grill finding #2).

NEVER edits a SKILL.md itself — advisory only. Approved rows are applied by
`writing-skills`, not by this script. Plugin-cache paths (any path segment literally
named `plugins`) are always excluded — this repo never audits skills it doesn't own.

Decline tracking: a JSON state file (default: alongside this script, `.audit-state.json`) records
`{skill_relpath: {finding_key: content_hash}}` so a re-run does not re-propose a finding the human
already declined for the SAME file content — editing the skill (content hash changes) clears the
decline for that finding.

Usage:
    audit.py [--root DIR] [--state-file PATH] [--json] [--no-state]
    audit.py --decline SKILL_RELPATH FINDING_KEY [--root DIR] [--state-file PATH]

Exit 0 always on a successful scan (even zero skills found); non-zero only on a hard usage error.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

CLAUDE_CODE_ONLY_FIELDS = ("model", "context", "effort", "agent", "background", "hooks", "paths")

JUDGMENT_WORDS = (
    "judge", "judgment", "evaluate", "assess", "decide", "consider", "weigh",
    "opinion", "critique", "subjective", "nuanced", "trade-off", "tradeoff",
    "compare", "recommend the best", "use your judgment",
)
DETERMINISTIC_HINTS = ("```bash", "```python", "```sh", "```py", "```js", "```ts")
BACKREFERENCE_WORDS = (
    "the conversation", "we discussed", "earlier in this session", "this session",
    "the file we", "as discussed", "the current conversation",
)
VERDICT_PATTERNS = (
    re.compile(r"^#{1,4}\s*verdict\b", re.I | re.M),
    re.compile(r"\bpass\s*/\s*fail\b", re.I),
    re.compile(r"\bpass\b.{0,20}\bfail\b", re.I),
    re.compile(r"^#{1,4}\s*(done|success)\s*criteria\b", re.I | re.M),
)
GOTCHAS_RE = re.compile(r"^#{1,4}\s*gotchas\b", re.I | re.M)
NUMBERED_STEP_RE = re.compile(r"^\s*\d+[.)]\s+\S", re.M)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n?", re.S)


def is_plugin_cache_path(path: Path) -> bool:
    return "plugins" in path.parts


def parse_frontmatter(text: str) -> dict:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fields = {}
    for line in m.group(1).splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key and not key[0].isspace() and key == key.lstrip():
            # top-level key (no leading indentation) — skip nested/list continuation lines
            if line[:1].isspace():
                continue
            fields[key] = value.strip()
    return fields


def body_without_frontmatter(text: str) -> str:
    m = FRONTMATTER_RE.match(text)
    return text[m.end():] if m else text


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def already_committed_nonportable(frontmatter: dict) -> bool:
    return any(f in frontmatter for f in CLAUDE_CODE_ONLY_FIELDS)


def recommend_model(frontmatter: dict, body: str):
    if "model" in frontmatter:
        return None, "already declares model: — no change proposed"
    lower = body.lower()
    has_judgment = any(w in lower for w in JUDGMENT_WORDS)
    has_script = any(h in lower for h in DETERMINISTIC_HINTS)
    if has_judgment:
        return None, "judgment-heavy — leave model unset (inherit)"
    if has_script:
        return "haiku", "deterministic/scripted steps, no evaluative language — grunt work fits haiku"
    return None, "ambiguous — no change proposed"


def context_fork_candidate(frontmatter: dict, body: str) -> bool:
    if "context" in frontmatter:
        return False
    lower = body.lower()
    return not any(w in lower for w in BACKREFERENCE_WORDS)


def has_extracted_script(skill_dir: Path) -> bool:
    """True when the mechanics are ALREADY extracted into a real script next to the SKILL.md — a
    `scripts/` dir holding at least one file, or an executable sibling. This — NOT an inline code
    fence — is what 'already has a script' means. A fenced ```bash block in prose is the extraction
    *signal* (mechanical steps sitting inline), so it must never be treated as an exemption (the
    census blind spot that hid github-solve-issues / ruff-fix; issue #154).
    """
    try:
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.is_dir() and any(p.is_file() for p in scripts_dir.iterdir()):
            return True
        for p in skill_dir.iterdir():
            if p.is_file() and p.name != "SKILL.md" and os.access(p, os.X_OK):
                return True
    except OSError:
        return False
    return False


def script_candidate(body: str, skill_dir: Path) -> bool:
    if has_extracted_script(skill_dir):
        return False  # mechanics already live in a real script — nothing to extract
    has_numbered_steps = len(NUMBERED_STEP_RE.findall(body)) >= 3
    # A fenced deterministic block IS the extraction signal, not an exemption — either it or a run of
    # numbered steps makes this a candidate for extraction into a script.
    has_deterministic_fence = any(h in body.lower() for h in DETERMINISTIC_HINTS)
    return has_numbered_steps or has_deterministic_fence


def missing_gotchas(body: str) -> bool:
    return GOTCHAS_RE.search(body) is None


def missing_verdict(body: str) -> bool:
    return not any(p.search(body) for p in VERDICT_PATTERNS)


ASKUQ_SIGNALS = ("choose", "which ", "select", "specify", "pick ", "option", "prefer")


def askuserquestion_candidate(frontmatter: dict, body: str) -> bool:
    low = body.lower()
    if "askuserquestion" in low:
        return False
    has_arg = "argument-hint" in frontmatter
    has_choice = any(w in low for w in ASKUQ_SIGNALS)
    return bool(has_arg or has_choice)


FINDING_KEYS = ("model", "context_fork", "script_candidate", "gotchas", "verdict", "askuserquestion")


def _skipped_row(skill_md: Path, root: Path, reason: str) -> dict:
    """Placeholder row for a SKILL.md that couldn't be read/parsed — carries the same keys as a
    normal row (so callers never have to special-case a missing key) but every finding defaults
    to falsy/None and `skipped`/`skip_reason` explain why. Never crashes the scan for this file.
    """
    return {
        "skill": skill_md.parent.name,
        "path": str(skill_md.relative_to(root)),
        "recommend_model": None,
        "model_reason": None,
        "context_fork_candidate": False,
        "script_candidate": False,
        "missing_gotchas": False,
        "missing_verdict": False,
        "portability_warning": False,
        "askuserquestion": False,
        "declined": [],
        "skipped": True,
        "skip_reason": reason,
    }


def build_row(skill_md: Path, root: Path, state: dict) -> dict:
    """Build one proposal row. Never raises for an unreadable/malformed file — a single bad
    SKILL.md must not crash the whole scan (contradicts the script's own "exit 0 always on a
    successful scan" contract, MEDIUM fix-forward post-#159); it's skipped + noted instead, and
    every other skill still gets scanned normally.
    """
    try:
        text = skill_md.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        return _skipped_row(skill_md, root, f"unreadable ({exc.__class__.__name__})")

    frontmatter = parse_frontmatter(text)
    body = body_without_frontmatter(text)
    relpath = str(skill_md.relative_to(root))
    h = content_hash(text)
    declined = state.get(relpath, {})

    model, model_reason = recommend_model(frontmatter, body)
    ctx_candidate = context_fork_candidate(frontmatter, body)
    committed_nonportable = already_committed_nonportable(frontmatter)
    portability_warning = (not committed_nonportable) and (model is not None or ctx_candidate)

    row = {
        "skill": frontmatter.get("name", skill_md.parent.name),
        "path": relpath,
        "recommend_model": model,
        "model_reason": model_reason,
        "context_fork_candidate": ctx_candidate,
        "script_candidate": script_candidate(body, skill_md.parent),
        "missing_gotchas": missing_gotchas(body),
        "missing_verdict": missing_verdict(body),
        "portability_warning": portability_warning,
        "askuserquestion": askuserquestion_candidate(frontmatter, body),
        "declined": [k for k in FINDING_KEYS if declined.get(k) == h],
        "skipped": False,
        "skip_reason": None,
    }
    return row


def find_skill_files(root: Path):
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("SKILL.md")
        if not is_plugin_cache_path(p.relative_to(root))
    )


def load_state(state_file: Path) -> dict:
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state_file: Path, state: dict) -> None:
    state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_table(rows: list) -> str:
    if not rows:
        return "No SKILL.md files found under the scanned root."
    lines = []
    for r in rows:
        if r.get("skipped"):
            lines.append(f"- {r['skill']} ({r['path']}): skipped (unreadable) — {r['skip_reason']}")
            continue
        flags = []
        if r["recommend_model"]:
            tag = f"model:{r['recommend_model']}"
            if r["portability_warning"] and "model" not in r["declined"]:
                tag += " ⚠non-portable-if-applied"
            if "model" not in r["declined"]:
                flags.append(tag)
        if r["context_fork_candidate"] and "context_fork" not in r["declined"]:
            tag = "context:fork candidate"
            if r["portability_warning"]:
                tag += " ⚠non-portable-if-applied"
            flags.append(tag)
        if r["script_candidate"] and "script_candidate" not in r["declined"]:
            flags.append("deterministic steps → script candidate")
        if r["missing_gotchas"] and "gotchas" not in r["declined"]:
            flags.append("missing ## Gotchas")
        if r["missing_verdict"] and "verdict" not in r["declined"]:
            flags.append("missing pass/fail verdict step")
        if r["askuserquestion"] and "askuserquestion" not in r["declined"]:
            flags.append("should gather input via AskUserQuestion")
        summary = "; ".join(flags) if flags else "no proposals (or all declined)"
        lines.append(f"- {r['skill']} ({r['path']}): {summary}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".claude/skills", help="Directory to scan (default: .claude/skills)")
    parser.add_argument("--state-file", default=None, help="Decline-state JSON path")
    parser.add_argument("--json", action="store_true", help="Emit JSON rows instead of a table")
    parser.add_argument("--no-state", action="store_true", help="Don't read/write decline state")
    parser.add_argument("--decline", nargs=2, metavar=("SKILL_RELPATH", "FINDING_KEY"))
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    script_dir = Path(__file__).resolve().parent
    state_file = Path(args.state_file).resolve() if args.state_file else script_dir / ".audit-state.json"

    if args.decline:
        relpath, finding_key = args.decline
        if finding_key not in FINDING_KEYS:
            print(f"error: unknown finding key {finding_key!r} — expected one of {FINDING_KEYS}", file=sys.stderr)
            return 2
        skill_path = root / relpath
        if not skill_path.exists():
            print(f"error: no such skill file under root: {relpath}", file=sys.stderr)
            return 2
        h = content_hash(skill_path.read_text(encoding="utf-8"))
        state = load_state(state_file)
        state.setdefault(relpath, {})[finding_key] = h
        save_state(state_file, state)
        print(f"declined {finding_key} for {relpath} (content {h})")
        return 0

    state = {} if args.no_state else load_state(state_file)
    rows = [build_row(p, root, state) for p in find_skill_files(root)]

    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
