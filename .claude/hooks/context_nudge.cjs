#!/usr/bin/env node
// SubagentStop context-nudge — non-blocking WARN when a subagent's returned text is large.
//
// A subagent should return a CONCISE SUMMARY to the primary session, not a dump — every character
// returned re-enters the primary's own context. Fires on SubagentStop, measures the subagent's
// final returned text (last_assistant_message); over threshold -> non-blocking systemMessage.
//
// No hook event exposes a subagent's SPAWN PROMPT, so this is RETURN-side detection only; the
// matching INPUT-side discipline is documented guidance in rules/agent-delegation.md, not a hook
// (see docs/superpowers/specs/2026-08-10-context-nudge-design.md).
//
// Threshold: default 16000 chars (~4k estimated tokens, chars/4), overridable via
// CONTEXT_NUDGE_RETURN_CHARS. Exclude specific agent_types via CONTEXT_NUDGE_EXCLUDE_AGENT_TYPES
// (comma-separated) — e.g. a crew report-writer role that legitimately returns large files.
//
// Never blocks. Fail-open on any error. Mirrors hooks/context_nudge.py exactly (parity asserted by
// tests/test_context_nudge.sh).

const DEFAULT_RETURN_CHARS = 16000
const CHARS_PER_TOKEN = 4

function threshold() {
  const raw = process.env.CONTEXT_NUDGE_RETURN_CHARS
  if (!raw || !raw.trim()) return DEFAULT_RETURN_CHARS
  const n = parseInt(raw, 10)
  return Number.isFinite(n) ? n : DEFAULT_RETURN_CHARS
}

function excludedAgentTypes() {
  const raw = process.env.CONTEXT_NUDGE_EXCLUDE_AGENT_TYPES || ''
  return new Set(raw.split(',').map((t) => t.trim()).filter(Boolean))
}

async function main() {
  let raw = ''
  process.stdin.setEncoding('utf8')
  for await (const chunk of process.stdin) raw += chunk

  let data
  try {
    data = JSON.parse(raw || '{}')
  } catch {
    process.exit(0)
  }

  if ((data && data.hook_event_name) !== 'SubagentStop') process.exit(0)

  const message = data.last_assistant_message
  if (typeof message !== 'string' || !message) process.exit(0)

  const agentType = data.agent_type || 'unknown'
  if (excludedAgentTypes().has(agentType)) process.exit(0)

  const chars = message.length
  if (chars <= threshold()) process.exit(0)

  const estKTokens = Math.max(1, Math.round(chars / CHARS_PER_TOKEN / 1000))
  process.stdout.write(
    JSON.stringify({
      systemMessage: `subagent (${agentType}) returned ~${estKTokens}k tokens — return a concise summary, not a dump.`,
    }) + '\n'
  )
  process.exit(0)
}

main().catch(() => {
  process.exit(0)
})
