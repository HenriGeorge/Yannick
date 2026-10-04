"""Bare-alias model guard (#178): an Agent/Task dispatch must not pass a bare alias via `model` —
it floats to the newest generation. Own module so #918 (wider denylist) is a one-file change."""
BARE_ALIASES = ("sonnet", "opus", "haiku", "fable")


def check(ctx):
    m = str(ctx.tool_input.get("model", "") or "").strip().lower()
    if m in BARE_ALIASES:
        return (
            f"Blocked: subagent dispatch passes model='{ctx.tool_input.get('model')}' — a bare "
            "alias floats to the newest model generation. OMIT `model` so the agent def's "
            "pinned exact ID wins; choose the model by choosing the agent type "
            "(rules/agent-delegation.md)."
        )
    return None
