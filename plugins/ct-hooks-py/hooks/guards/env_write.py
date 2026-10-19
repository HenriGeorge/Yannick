"""Block overwriting .env via a shell redirect (hook consolidation PR 5)."""
BLOCKED_WRITE_PATTERNS = [".env"]


def check(ctx):
    # Block writing to .env
    for pattern in BLOCKED_WRITE_PATTERNS:
        if any(op in ctx.command for op in [f"> {pattern}", f">> {pattern}", f"cat > {pattern}"]):
            return f"Blocked: do not overwrite {pattern} via shell."
    return None
