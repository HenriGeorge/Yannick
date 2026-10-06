---
name: hook-creator
description: 'Use when authoring, wiring, or verifying a new deterministic hook in the claude_template repo — a PreToolUse/PostToolUse/Stop/SessionStart/Worktree* guard, gate, or nudge. Covers the real Claude Code hook contract (stdin JSON, exit codes, fail-open) and this repo''s py+node twin → registry → sync → parity pipeline. Triggers on "add a hook", "new gate/guard/nudge", "wire a hook", "block on <tool>".'
---

# Hook Creator

Author a new deterministic hook for **this template repo** — correctly wired into the py **and** node
plugin stacks, registry-generated, and parity-tested. A hook is a runtime guard the harness enforces;
it is NOT a skill and NOT prose guidance.

**Core principle:** a hook is the *enforcement* layer. If a guardrail can be checked deterministically
at a tool call (a regex, a file-exists, a JSON field), it's a hook. If it needs judgment or taste,
it's a **rule** (`rules/*.md`), not a hook. See `HOOKS.md`'s rules-vs-hooks boundary.

## When to use

- Blocking a tool call on a deterministic condition (a `git commit` missing a section, a raw suite run).
- A non-blocking WARN at a turn boundary (a plan written without grill findings).
- Injecting context at session start, or reacting to a Worktree/Teammate lifecycle event.

**When NOT to use** — a judgment call ("prefer editing over creating"), a style preference, anything a
regex can't decide. That's a rule, enforced by goodwill + review, not a hook.

## The real Claude Code hook contract

> ⚠️ Ignore any generic "hooks.json with event/when/command/filter and `$FILE`/`$TOOL` variables"
> template — that schema is fabricated and does not exist. The real contract is below.

**A hook is a script that reads a JSON payload on stdin and signals via exit code + stdout JSON.**

### Event names (exact — no `tool-call`/`when: before|after`)

| Event | Fires | Can block? |
|---|---|---|
| `PreToolUse` | before a tool runs | **yes** — deny the call |
| `PostToolUse` | after a tool runs | no — WARN only |
| `UserPromptSubmit` | on prompt submit | injects context |
| `SessionStart` / `SessionEnd` | session bounds | injects context |
| `Stop` / `SubagentStop` | turn/agent end | **yes** — via exit code |
| `PreCompact` | before compaction | no |
| `WorktreeCreate` / `WorktreeRemove` / `TeammateIdle` | lifecycle (this repo's runner) | **yes** — via exit code |

### stdin payload (read it, don't guess env vars)

```python
data = json.loads(sys.stdin.read() or "{}")
tool = data.get("tool_name", "")                       # "Bash", "PowerShell", "Write", "Edit", ...
cmd  = data.get("tool_input", {}).get("command", "")   # Bash and PowerShell
path = data.get("tool_input", {}).get("file_path", "") # Write/Edit
cwd  = data.get("cwd", "")
```

There is no `$FILE` / `$TOOL` / `$PROJECT`. The env you *do* get: `${CLAUDE_PROJECT_DIR}`,
`${CLAUDE_PROJECT_DIR}/.claude` (resolves to the plugin's install dir at runtime).

### Decision protocol

| Intent | How |
|---|---|
| **Allow** (and always on error) | `sys.exit(0)` — **fail open**, never brick a session |
| **Block a PreToolUse call** | print the dual-form JSON below, print reason to `stderr`, `sys.exit(2)` |
| **Non-blocking WARN** | `print(json.dumps({"systemMessage": NOTICE}))`, `sys.exit(0)` |

```python
# PreToolUse deny — emit BOTH forms so older harnesses keep working
print(json.dumps({
    "decision": "block",                      # deprecated top-level form
    "reason": reason,
    "hookSpecificOutput": {                    # current form
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    },
}))
print(reason, file=sys.stderr)                 # documented feedback channel on exit 2
sys.exit(2)
```

**Fail-open is mandatory.** Wrap the body so malformed stdin / missing file / any exception →
`sys.exit(0)` silently. A hook that crashes on a bad payload bricks every tool call.

## Authoring pipeline (this repo)

Every hook is a **py + node twin** — the canonical sources live directly in the plugins:
`plugins/claude-template-hooks-py/hooks/*.py` and `plugins/claude-template-hooks-node/hooks/*.cjs`
(no separate `hooks/` source layer, no sync of hook bundles). Wiring is **generated** from
`hook-wiring/registry/*.json`, not hand-written.

1. **Design first (GATE-1).** Decide event, matcher (tool regex), block-vs-warn, and the bypass token
   if it blocks (`WORKFLOW:no-<name>`). A blocking gate needs a bypass for the genuinely-trivial case.
2. **Write `plugins/claude-template-hooks-py/hooks/<name>.py`** — PEP-723 header, stdlib only:
   ```python
   #!/usr/bin/env -S uv run --script
   # /// script
   # requires-python = ">=3.11"
   # dependencies = []
   # ///
   ```
   Follow the contract above. `plugins/claude-template-hooks-py/hooks/grill_nudge.py` (WARN) and
   `plugins/claude-template-hooks-py/hooks/grill_gate.py` (BLOCK) are the reference shapes to mirror.
3. **Write the node twin `plugins/claude-template-hooks-node/hooks/<name>.cjs`** — a byte-for-byte
   *behavioral* mirror (Node core modules only). A port has an oracle: mirror the code, mirror the
   test (lesson #282).
4. **Add the registry fragment `hook-wiring/registry/<name>.json`:**
   ```json
   {
     "id": "<name>",
     "wirings": [
       { "event": "PostToolUse", "matcher": "Write|Edit", "command_key": "HOOK_<NAME>", "order": 30 }
     ]
   }
   ```
5. **Generate wiring:** `bin/build-hook-wiring.sh` (regenerates `hook-wiring/canonical-settings-hooks.json`
   + both plugins' `hooks/hooks.json` from the registry) — or `bash bin/sync-generated.sh` for the full
   derived-artifact chain. Never edit the generated wiring by hand.
6. **Test:** add a standalone `tests/test_<name>.sh` case (must be able to fail — cover block AND
   allow), and extend `tests/test_plugin_hooks_parity.sh` so every py-only assertion gets a symmetric
   node counterpart. Lint: `uvx ruff check plugins/claude-template-hooks-py/hooks/` + `shellcheck` the test.

## Common mistakes (the fabricated-schema traps)

| ❌ Wrong (generic template) | ✅ Right (real contract) |
|---|---|
| `event: "tool-call"`, `when: "before"` | separate `PreToolUse` / `PostToolUse` events, no `when` |
| flat `hooks.json` with `name/command/filter` | nested `{Event:[{matcher, hooks:[{type,command}]}]}`, generated from registry |
| `filter: {filePattern, promptPattern}` | only `matcher` (regex on tool name); filter paths *inside* the script |
| `$FILE` / `$TOOL` in the command | read `tool_input.file_path` / `tool_name` from stdin JSON |
| adding a `version:` frontmatter field | frontmatter is `name` + `description` only |
| edit only the py hook | **both** twins + registry + sync, or the parity test fails |
| edit a hook (even a docstring/comment) without a version bump | any content change needs a plugin **version bump** (both `plugin.json` + both `marketplace.json` entries) + `bin/hooks-fingerprint.sh --write`, or PH-08 (content↔fingerprint) and PH-01b (versions equal) go red — bump only at the merge slot / the train's release step, never in a fix round; the `pluginver` merge driver resolves a version-only conflict to max+1 and leaves the fingerprint as a conflict to regenerate |
| crash on bad input | fail-open exit 0, with degraded paths surfaced via a stdout `systemMessage` |

## Verify (GATE-2)

Run this turn, show the output:

```bash
uvx ruff check hooks/<name>.py
bash tests/test_<name>.sh                 # your new case — block AND allow paths
bash tests/test_plugin_hooks_parity.sh    # twin/wiring parity
```

Iterate on those case files only. The full suite runs once, as the a full suite per PR for a tier-2 PR (tier-0/1 gates on the affected slice), at the
final synced head and under the lock: `bin/test-lock --wait [--timeout N] -- bash tests/run.sh`. A fix round re-runs only
these case files, unless it also edits `setup.sh`, `propagate.sh`, or `tests/run.sh` (then a full run).

## Gotchas

- PowerShell tool: same `tool_input.command`; match `Bash|PowerShell`; never `if: PowerShell(…)` (#57137); run commands through `_lib.shell.ps_to_sh` before bash-style parsing.

## See also

`plugins/claude-template-core/docs/workflow/HOOKS.md` (the per-hook catalog — what each existing hook
does + the rules-vs-hooks boundary) · `ENFORCEMENT.md` (the gate roster: what BLOCKs, what WARNs, every
`WORKFLOW:no-*` token) · `writing-skills` (this skill was authored through it) ·
`shell-scripting` (harden the test case) · `hooks/grill_nudge.py` / `hooks/grill_gate.py` (reference
WARN + BLOCK shapes).
