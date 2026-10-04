---
description: "Arm the autopilot lane on a plan — verify it declares autonomy: unattended with unchecked boxes, then export CLAUDE_UNATTENDED_ANSWER=1 so a cloud peer answers reversible forks unattended while the safety floor still DENIES the rest."
argument-hint: "<plan-path>"
---

# /autopilot — arm the unattended build lane on a plan

**Arg**: `$ARGUMENTS` → `<plan-path>` (required). One command arms the whole autopilot lane:
`build_loop` drives the plan, and `unattended_answer` fields the AskUserQuestion forks a cloud peer
can safely answer.

This is `build_loop`'s **plain-checkbox lane** — a plan declaring `autonomy: unattended` in
front-matter with unchecked `- [ ]` boxes. There is **no `gates:` ledger and no gate executor**: the
`gates` skill's `claude-template gate-run` executor (now reachable downstream via the dispatcher,
#711) is a separate gate-verified lane this one deliberately avoids. "Done" is the plan's boxes
ticked, not a command ledger.

## Run it

1. **Verify the precondition.** Read `<plan-path>` and confirm BOTH hold:
   - its front-matter declares `autonomy: unattended`, and
   - it still has at least one unchecked `- [ ]` box.

   ```bash
   plan="$ARGUMENTS"
   head -20 "$plan" | grep -q '^autonomy: unattended' && grep -q '^- \[ \]' "$plan" \
     && echo "armable" || echo "NOT armable"
   ```

   If the boxes are present but the `autonomy: unattended` flag is missing, **offer to add it** to
   the front-matter (don't add it silently) — arming a plan the author didn't mark unattended is a
   judgment call, not a mechanical one. If there are no unchecked boxes, stop: nothing to drive.

2. **Arm the lane.** Export the safety-gate flag for this session:
   ```bash
   export CLAUDE_UNATTENDED_ANSWER=1
   ```
   This is what makes `unattended_answer` engage its peer tiering. With the flag OFF (the default),
   every AskUserQuestion still prompts a human — arming is the deliberate opt-in.

3. **State the lane is armed** and hand off to `build_loop`: it re-feeds the next unchecked `- [ ]`
   item on each stop until the plan is complete, then self-disarms. Terminators (budget, stall,
   livelock) still park to `.claude/NEEDS-HUMAN.md`.

## The cloud peer — `AUTOPILOT_PEER`

`unattended_answer` asks the peer model in `AUTOPILOT_PEER` (default `glm-5.3:cloud`, set in
`.claude/worktrees.conf`) to answer a **reversible** fork; irreversible/destructive forks are always
DENIED regardless. Override per-repo by editing that key, or per-session with
`export AUTOPILOT_PEER=<model>`.

The peer runs on **Ollama Cloud** via the native Anthropic API at `http://127.0.0.1:11434` —
`AUTOPILOT_PEER` drives the hook directly. It is **CLOUD-only: never the local GPU** — the local
GPU peer was too slow to be usable and is not supported. Setup once (only `glm-5.2:cloud` ships
pulled by default):

```bash
ollama pull glm-5.3:cloud
```

**Gotcha:** `claude-code-router`'s default route is a *local* mlx model, NOT the cloud peer —
`AUTOPILOT_PEER` bypasses `ccr` and talks to Ollama Cloud directly, so the router's default never
applies here.

## Per-task parking — `AUTOPILOT_TASK_ID` (known limitation)

When the peer can't safely answer, `unattended_answer` writes a questionnaire tagged
`task: <AUTOPILOT_TASK_ID>` (default `unknown`) and DENIES the fork; `build_loop` parks a box only
when that id **matches the box it's driving**. So:

- **`AUTOPILOT_TASK_ID` unset** → escalations still safely **DENY** the fork (the safety floor holds),
  but the loop can't cleanly park-and-continue that specific task — it re-feeds instead.
- **`AUTOPILOT_TASK_ID` set to the driven task's id** (per driven task) → escalations park that box
  and the loop moves on.

Full per-task env-threading is a known follow-up (G6); this command does not attempt it.
