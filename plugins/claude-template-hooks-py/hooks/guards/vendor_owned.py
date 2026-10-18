"""Redirect a plugin-sourced `.claude/` copy edit to its `plugins/` source (source repo only).

Post-devendor (#1296): there is no lock file. A `.claude/<kind>/<rest>` path is plugin-owned iff
`plugins/<plugin>/<kind>/<rest>` exists on disk — a lock-free lookup that replaces the retired
vendored_entries() map. The old fleet-side "edit upstream" block is gone: the fleet now receives
`plugins/` by copy-delivery (T6), so a consumer repo has no materialized copies to protect.
"""

import os

from _lib.git import GIT_COMMIT_INVOCATION_RE, _git_show_toplevel, _staged_names
from _lib.shell import _process_env_override

BYPASS = "CT_ALLOW_TEMPLATE_EDIT"

# .claude/<kind>/… mirrors plugins/<plugin>/<kind>/… for these plugin-owned kinds. A .claude/ copy
# is a materialized duplicate; the canonical source is under plugins/, so editing the copy is a
# no-op the next delivery overwrites. (.claude/rules is a symlink → repo-root rules/, so realpath in
# _rel resolves it outside .claude/ and it is never matched here — rules are canonical at root.)
_MIRRORED_KINDS = ("hooks/", "skills/", "commands/", "agents/")


def _rel(root, project_dir, file_path):
    abs_path = file_path if os.path.isabs(file_path) else os.path.join(project_dir or root, file_path)
    try:
        rel = os.path.relpath(os.path.realpath(abs_path), os.path.realpath(root))
    except Exception:  # noqa: BLE001 - never brick a session on a bad path
        return None
    return None if rel.startswith("..") else rel.replace("\\", "/")


def _plugin_source_for(root, rel):
    # (plugin, after) if rel is a .claude/ copy of a plugins/ source, else None. Lock-free (#1296).
    if not rel.startswith(".claude/"):
        return None
    after = rel[len(".claude/"):]
    if not after.startswith(_MIRRORED_KINDS):
        return None
    plugins_dir = os.path.join(root, "plugins")
    try:
        for plugin in sorted(os.listdir(plugins_dir)):
            if os.path.exists(os.path.join(plugins_dir, plugin, after)):
                return plugin, after
    except OSError:  # no plugins/ dir → nothing to redirect to → fail open
        return None
    return None


def _is_source_repo(root):
    return os.path.exists(os.path.join(root, ".claude-plugin", "marketplace.json"))


def _block(file_path, project_dir):
    if not file_path or _process_env_override(BYPASS):
        return
    root = _git_show_toplevel(project_dir) or project_dir
    if not root or not _is_source_repo(root):
        return
    rel = _rel(root, project_dir, file_path)
    if rel is None:
        return
    hit = _plugin_source_for(root, rel)
    if not hit:
        return
    plugin, after = hit
    return (
        f"Blocked: {rel} is a materialized copy, regenerated from the plugin source. Edit the real "
        f"source at plugins/{plugin}/{after} instead. Override just this edit with {BYPASS}=1."
    )


def check(ctx):
    return _block(ctx.tool_input.get("file_path", ""), ctx.project_dir)


def check_commit(ctx):
    command = ctx.tool_input.get("command", "")
    # GIT_COMMIT_INVOCATION_RE is the shared detector (matches `git -C <path> commit`, R8), used by
    # every other commit-touching guard (H2/H3/H6/H9/H10).
    if not GIT_COMMIT_INVOCATION_RE.search(command) or _process_env_override(BYPASS):
        return
    root = _git_show_toplevel(ctx.project_dir) or ctx.project_dir
    if not root or not _is_source_repo(root):
        return
    for rel in _staged_names(root):
        hit = _plugin_source_for(root, rel)
        if not hit:
            continue
        plugin, after = hit
        return (
            f"Blocked: commit stages {rel}, a materialized copy. Commit the change to "
            f"plugins/{plugin}/{after} instead. Override with {BYPASS}=1."
        )
    return
