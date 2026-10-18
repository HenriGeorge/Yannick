#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""context-floor-audit scan — deterministic half of the `/context-floor-audit` skill (issue #8).

Scans a project root for the three components of its baseline ("floor") context load:
  - `mcp_servers`  — the sorted union of `mcpServers` keys declared in `<root>/.mcp.json` AND
                      `<root>/.claude/settings.json` (either file missing or unparseable
                      contributes nothing — never raises).
  - `skills`       — one `{"name": ..., "desc_chars": ...}` row per `**/SKILL.md` under root,
                      excluding any path with a `plugins` path segment (plugin-cache-shaped,
                      never owned by this repo — same exclusion as skill-audit's
                      `is_plugin_cache_path`).
  - `claude_md_lines` — line count of `<root>/CLAUDE.md` (0 if absent).

Recommend-only: this is a READ/scan script. It never edits or deletes anything.

Usage:
    scan.py [--root DIR] [--json]

Exit 0 always on a successful scan (even zero of everything); non-zero only on a hard usage
error (e.g. an unrecognized flag — argparse's own exit code).
"""
import argparse
import json
import re
from pathlib import Path

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
        if line[:1].isspace():
            # nested/list continuation line — not a top-level key
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            fields[key] = value.strip()
    return fields


def load_mcp_servers(path: Path) -> set:
    """Read the `mcpServers` object's keys from a JSON file. Fail-open: a missing file, a parse
    error, or an unexpected shape all contribute nothing rather than raising."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return set()
    return set(servers.keys())


def scan_mcp_servers(root: Path) -> list:
    servers = set()
    servers |= load_mcp_servers(root / ".mcp.json")
    servers |= load_mcp_servers(root / ".claude" / "settings.json")
    return sorted(servers)


def scan_skills(root: Path) -> list:
    rows = []
    if not root.exists():
        return rows
    for skill_md in sorted(root.rglob("SKILL.md")):
        try:
            relpath = skill_md.relative_to(root)
        except ValueError:
            continue
        if is_plugin_cache_path(relpath):
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        frontmatter = parse_frontmatter(text)
        name = frontmatter.get("name", skill_md.parent.name)
        desc = frontmatter.get("description", "")
        rows.append({"name": name, "desc_chars": len(desc)})
    return rows


def scan_claude_md_lines(root: Path) -> int:
    claude_md = root / "CLAUDE.md"
    try:
        text = claude_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    if text == "":
        return 0
    return len(text.splitlines())


def build_scan(root: Path) -> dict:
    return {
        "mcp_servers": scan_mcp_servers(root),
        "skills": scan_skills(root),
        "claude_md_lines": scan_claude_md_lines(root),
    }


def render_table(scan: dict) -> str:
    lines = [
        f"mcp_servers ({len(scan['mcp_servers'])}): {', '.join(scan['mcp_servers']) or '(none)'}",
        f"claude_md_lines: {scan['claude_md_lines']}",
        f"skills ({len(scan['skills'])}):",
    ]
    for s in scan["skills"]:
        lines.append(f"  - {s['name']}: {s['desc_chars']} desc chars")
    if not scan["skills"]:
        lines.append("  (none)")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Project root to scan (default: .)")
    parser.add_argument("--json", action="store_true", help="Emit a JSON object instead of a table")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    scan = build_scan(root)

    if args.json:
        print(json.dumps(scan, indent=2, sort_keys=True))
    else:
        print(render_table(scan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
