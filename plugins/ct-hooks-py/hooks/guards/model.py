"""Model allow-list guard (#178/#918): an Agent/Task dispatch must pass ONLY an exact pinned model
ID via `model` — anything else (a bare alias `sonnet`/`opus`/…, `opusplan`, `default`, a `[1m]`-
suffixed alias) floats to the newest generation. Inverted to an allow-list (#918) so a NEW floating
alias is DENIED by default: allow only the exact-pinned-ID SHAPE `claude-<family>-<version>…`."""
import re

# An exact pinned ID: starts `claude-`, a family word, then a numeric version tail — no bracket
# suffix (a `[1m]` suffix is a floating variant, not a pin). Everything else is denied by default.
_PINNED_ID = re.compile(r"^claude-[a-z]+-[0-9][a-z0-9-]*$")


def check(ctx):
    m = str(ctx.tool_input.get("model", "") or "").strip().lower()
    if m == "" or _PINNED_ID.match(m):
        return None
    return (
        f"Blocked: subagent dispatch passes model='{ctx.tool_input.get('model')}' — not an exact "
        "pinned model ID. A bare alias / opusplan / default / [1m]-suffixed alias floats to the "
        "newest model generation. OMIT `model` so the agent def's pinned exact ID wins; choose the "
        "model by choosing the agent type (rules/agent-delegation.md)."
    )
