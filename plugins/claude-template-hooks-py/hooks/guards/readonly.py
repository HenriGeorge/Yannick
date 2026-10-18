"""Read-only paths — no `rm -rf` inside one (Bash) and no Write/Edit into one (hook consolidation PR 5).
The list itself (code baseline READONLY_PATHS + the readonly seam) is built by the entry and passed
in as ctx.readonly_paths."""


def check_bash(ctx):
    # Block rm -rf on read-only paths (baseline + seam-appended)
    for path in ctx.readonly_paths:
        if "rm -rf" in ctx.command and path in ctx.command:
            return f"Blocked: cannot rm -rf inside {path} — read-only."
    return None


def check_write(ctx):
    file_path = ctx.tool_input.get("file_path", "")
    for path in ctx.readonly_paths:
        if path in file_path or file_path.endswith(path.rstrip("/")):
            return f"Blocked: {path} is read-only. Cannot write to {file_path}"
    return None
