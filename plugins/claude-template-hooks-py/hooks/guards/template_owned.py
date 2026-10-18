"""Layer A — block an in-place Edit/Write to a pristine template-owned file (hook consolidation PR 5)."""

import hashlib
import os
import sys

from _lib.git import _git_show_toplevel
from _lib.shell import _process_env_override


def _template_owned_block(file_path: str, project_dir: str):
    """Layer A — BLOCK an in-place Edit/Write to a template-OWNED file inside a managed project.
    Template-owned = listed in <root>/.claude/template-manifest.tsv AND still byte-identical to the
    recorded install hash (a pristine template reference). A project that already forked the file
    (hash differs) is allowed; a project-authored file (not in the manifest) is allowed; the template
    repo itself (marketplace marker, no manifest) is exempt. Fail-open on anything unexpected.
    Bypass: CT_ALLOW_TEMPLATE_EDIT=1."""
    if not file_path or _process_env_override("CT_ALLOW_TEMPLATE_EDIT"):
        return
    root = _git_show_toplevel(project_dir) or project_dir
    if not root:
        return
    # The template repo itself is exempt — editing template-owned files there is correct.
    if os.path.exists(os.path.join(root, ".claude-plugin", "marketplace.json")):
        return
    manifest = os.path.join(root, ".claude", "template-manifest.tsv")
    if not os.path.isfile(manifest):
        return  # unscaffolded / no manifest → fail-open
    abs_path = file_path if os.path.isabs(file_path) else os.path.join(project_dir or root, file_path)
    try:
        rel = os.path.relpath(os.path.realpath(abs_path), os.path.realpath(root))
    except Exception:  # noqa: BLE001
        return
    if rel.startswith(".."):
        return  # outside the repo → not ours to guard
    recorded = None
    try:
        with open(manifest, encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 2 and parts[0] == rel:
                    recorded = parts[1]
                    break
    except OSError as exc:
        # Manifest exists but is unreadable — a breadcrumb, since this silently stops protecting the
        # whole repo (fail-open is still correct; a corrupt ledger must never brick a session).
        sys.stderr.write(f"[pre_tool_use] template-manifest unreadable ({exc!r}) — ownership guard off\n")
        return
    if recorded is None:
        return  # not a template-installed file → allow
    try:
        with open(abs_path, "rb") as fh:
            current = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return  # can't read (e.g. brand-new file) → fail-open
    if current != recorded:
        return  # project already forked this file → allow the edit
    return (
        f"Blocked: {rel} is a template-owned reference file (managed by claude_template). Change it "
        "upstream in the claude_template repo — it flows down via propagate.sh — or make your own "
        "project-specific file. Override just this edit with CT_ALLOW_TEMPLATE_EDIT=1."
    )


def check(ctx):
    return _template_owned_block(ctx.tool_input.get("file_path", ""), ctx.project_dir)
