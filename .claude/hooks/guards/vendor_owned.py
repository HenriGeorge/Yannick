"""Block editing a vendored claude-template file; redirect to plugin source in the source repo."""

import os

from _lib.git import GIT_COMMIT_INVOCATION_RE, _git_show_toplevel, _staged_names
from _lib.shell import _process_env_override
from _lib.vendor_lock import vendored_entries

BYPASS = "CT_ALLOW_TEMPLATE_EDIT"


def _rel(root, project_dir, file_path):
    abs_path = file_path if os.path.isabs(file_path) else os.path.join(project_dir or root, file_path)
    try:
        rel = os.path.relpath(os.path.realpath(abs_path), os.path.realpath(root))
    except Exception:  # noqa: BLE001 - never brick a session on a bad path
        return None
    return None if rel.startswith("..") else rel.replace("\\", "/")


def _note_corrupt_lock(ctx, label, err):
    # I1 (silent-failure-hunter): a corrupt vendor.lock disables the guard — surface it on the
    # allow path exactly like nocommit_guard/tdd_gate do for the sibling vendored_paths() note,
    # so it's visible (ctx.notes → the allow-path systemMessage), not a silent fail-open.
    notes = getattr(ctx, "notes", None)
    if err and isinstance(notes, list):
        notes.append(f"{label}: {err}")


def _block(ctx, file_path, project_dir):
    if not file_path or _process_env_override(BYPASS):
        return
    root = _git_show_toplevel(project_dir) or project_dir
    if not root:
        return
    entries, err = vendored_entries(root)
    _note_corrupt_lock(ctx, "vendor_owned", err)
    if err or not entries:
        return  # no/corrupt vendor.lock → fail-open
    rel = _rel(root, project_dir, file_path)
    if rel is None:
        return
    is_source = os.path.exists(os.path.join(root, ".claude-plugin", "marketplace.json"))
    if is_source:
        entry = entries.get(rel)
        if not isinstance(entry, dict):
            return  # None (allow) or malformed entry → fail open
        plugin = entry.get("plugin", "the plugin")
        after = rel[len(".claude/"):] if rel.startswith(".claude/") else rel
        return (
            f"Blocked: {rel} is a vendored copy, regenerated from the plugin source. Edit the real "
            f"source at plugins/{plugin}/{after} instead (it re-vendors into .claude/). Override just "
            f"this edit with {BYPASS}=1."
        )
    if rel == ".claude/vendor.lock" or rel in entries:
        return (
            f"Blocked: {rel} is a vendored claude-template file (canonical in the claude_template "
            "repo). Edit it upstream there — it flows down via `propagate.sh --apply` — or make a "
            f"project-specific file. Override just this edit with {BYPASS}=1."
        )
    return


def check(ctx):
    return _block(ctx, ctx.tool_input.get("file_path", ""), ctx.project_dir)


def check_commit(ctx):
    command = ctx.tool_input.get("command", "")
    # M2: a bare `"git commit" in command` substring test misses this repo's standard cross-repo
    # form `git -C <path> commit` (R8) — GIT_COMMIT_INVOCATION_RE is the shared detector every
    # other commit-touching guard (H2/H3/H6/H9/H10) already uses for exactly this reason.
    if not GIT_COMMIT_INVOCATION_RE.search(command) or _process_env_override(BYPASS):
        return
    root = _git_show_toplevel(ctx.project_dir) or ctx.project_dir
    if not root:
        return
    entries, err = vendored_entries(root)
    _note_corrupt_lock(ctx, "vendor_owned", err)
    if err or not entries:
        return
    is_source = os.path.exists(os.path.join(root, ".claude-plugin", "marketplace.json"))
    # I2: _staged_names is the SHARED helper (H6/H9/H10 use it too) — routed through run_memo, so a
    # failed git read (timeout/non-zero/throw) is recorded in _lib.git.failed_labels and surfaced by
    # pre_tool's _append_git_notes on the allow path, instead of a silent blind-allow.
    for rel in _staged_names(root):
        if is_source:
            if rel in entries:
                entry = entries.get(rel)
                plugin = entry.get("plugin", "the plugin") if isinstance(entry, dict) else "the plugin"
                after = rel[len(".claude/"):] if rel.startswith(".claude/") else rel
                return (
                    f"Blocked: commit stages {rel}, a vendored copy. Commit the change to "
                    f"plugins/{plugin}/{after} instead, then re-vendor. Override with {BYPASS}=1."
                )
        elif rel == ".claude/vendor.lock" or rel in entries:
            return (
                f"Blocked: commit stages {rel}, a vendored claude-template file. Change it upstream "
                f"in the claude_template repo (flows down via propagate.sh --apply). Override with {BYPASS}=1."
            )
    return
