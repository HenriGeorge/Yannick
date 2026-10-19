---
name: local-model-runners
description: Use when running Claude Code on a local or cheaper model via the ~/.zshrc runner functions (glmcode, glmollama, kimicode, localchat, qexp, opscode), choosing a cheap-agent lane for triage/doc drafts/mechanical passes, configuring Ollama or claude-code-router, or setting up the autopilot cloud peer (AUTOPILOT_PEER). Not for ordinary sessions on the default model.
---

# Local-model runners (the cheap-agent lane)

Last updated: 2026-10-19 12:58

Machine-global shell functions in `~/.zshrc` that run Claude Code on local / cheaper models. Reach
for these for **cheap or free agent work** (triage, doc drafts, mechanical passes, local-model
experiments) instead of re-deriving `ANTHROPIC_BASE_URL` env vars by hand. Available in every repo.

All are **lean by default** (`--bare --strict-mcp-config` = no hooks/LSP/plugins/MCP) except
`opscode`. Plain `claude` is untouched and keeps every skill + MCP — never route judgment roles
(REVIEW / silent-failure / design / the implementer's TDD build) down to a local model; those stay
on plain `claude` (see `agent-delegation.md` model-routing).

| Function | Endpoint | Model | Cost | Mode |
|----------|----------|-------|------|------|
| `glmcode` | claude-code-router (`ccr`) `:3456` | router default | — | lean |
| `glmollama` | Ollama `:11434` (native Anthropic API) | `glm-4.7-flash:180k` | free (local) | lean |
| `kimicode` | Ollama `:11434` | `kimi-k3:cloud` | PAID (Ollama Cloud) | lean |
| `localchat` | Ollama `:11434` | `qwen3-coder:30b-128k` | **free, on-disk** | lean |
| `qexp` | Ollama `:11434` | `qwen3:30b-16k` | **free, on-disk** | lean |
| `opscode` | Ollama `:11434` | `glm-5.2:cloud` | PAID (cloud) | **full** (skills+MCP) |
| _autopilot peer_ | Ollama `:11434` | `glm-5.3:cloud` (`AUTOPILOT_PEER`) | PAID (cloud) | second-opinion consult (not interactive) |

- **`glmcode` gotcha:** `ccr`'s *default* route is **mlx, not ollama glm** — so `glmcode` alone does
  NOT hit local GLM unless you flip `~/.claude-code-router/config.json`
  `"Router": { "default": "ollama,glm-4.7-flash:180k" }` then `ccr restart`. The **`glmollama`**
  direct path avoids the daemon entirely (run `ollama serve` first) — prefer it for local GLM.
- **`glmollama`** is defined in `~/.zshrc` (added 2026-08-27), sitting right after the `glmcode` block.
- **`qexp` gotcha (why not phi4):** `qexp` is a general local-model experiment lane. It was meant for
  phi4, but **Ollama's phi4 does NOT support tool-calling** (`phi4 does not support tools`), so Claude
  Code — which needs tools for Bash/Edit/Write — cannot run on it at all. `qwen3:30b-16k` is
  tool-capable; swap `ANTHROPIC_MODEL` only for another **tool-capable** local model, never phi4.

**Security (from the zshrc comments):** these give a local/remote UNVETTED model Claude Code's full
Bash/Edit/Write. Only feed TRUSTED input; never untrusted/pasted content on a write-access repo — run
untrusted input in a scratch dir or a restricted permission mode. Cloud lanes (`kimicode`, `opscode`,
`kimi-k3:cloud`) are remote — treat as such, keep sensitive prompts on the local `:11434` lanes.

Same precedent as the `kimi()` / `--local` Ollama form already in the `github-solve-issues` skill.

## Autopilot peer (the `unattended_answer` cloud consult)

The claude_template autopilot lane's `unattended_answer` hook consults a **cloud** peer as a
*second opinion* on an uncovered execution fork — a different model's take, not an oracle. Config:

- **`AUTOPILOT_PEER`** (default **`glm-5.3:cloud`**) — Ollama Cloud, native Anthropic API on `:11434`.
  `ollama pull glm-5.3:cloud` first (only `glm-5.2:cloud` ships by default). Mirror an `opscode`-style
  cloud runner if you want it interactively (`ANTHROPIC_BASE_URL=http://127.0.0.1:11434`,
  `ANTHROPIC_MODEL=glm-5.3:cloud`).
- **Cloud only — never the local GPU.** The local-GPU path was slow and did not work for this; the
  peer must be a `:cloud` model. Reversible forks → the peer answers; load-bearing/irreversible or
  any peer error → escalate (never guess).
- **Gotcha:** `claude-code-router`'s default route is a *local* mlx model, NOT the cloud peer — so a
  bare `ccr`/`glmcode` path does not reach the autopilot peer. `AUTOPILOT_PEER` drives the hook
  directly via Ollama, bypassing `ccr`.
