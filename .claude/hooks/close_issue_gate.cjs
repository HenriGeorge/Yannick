#!/usr/bin/env node
// Stop hook (Node) — CLOSE issue-filing gate.
//
// Enforces: a session that made real git commits must file follow-up GitHub issues
// (or explicitly declare there are none) before it's allowed to stop.
//
// Reads the Stop-hook JSON payload from stdin (fields: transcript_path, session_id,
// stop_hook_active), then scans the session transcript (JSONL — one event per line) for:
//   - made_commit:   a Bash tool_use command containing "git commit"
//   - filed_issue:   a Bash tool_use command containing "gh issue create"
//   - declared_none: assistant text containing the exact sentinel "WORKFLOW:no-follow-ups"
//
// If made_commit and neither filed_issue nor declared_none: block the stop with a JSON
// decision on stdout. Otherwise allow the stop silently.
//
// Deliberately does NOT short-circuit on stop_hook_active: the sentinel/issue-filing is the
// escape hatch, so a cooperating agent satisfies the gate on its next attempt and this can't
// infinite-loop. (An uncooperative agent could loop, but that's true of any blocking Stop
// hook and out of scope here.)
//
// Never crashes: any exception, missing/unreadable transcript_path, or malformed JSON
// results in a silent exit 0 (best-effort, matches stop_log.cjs).

const fs = require('node:fs')
const readline = require('node:readline')

const BLOCK_REASON =
  'CLOSE gate ⛔ — this session committed changes but filed no GitHub ' +
  'issues for follow-ups/known gaps. Run `gh issue create` for each deferred ' +
  'item, or if there are genuinely none, state exactly: WORKFLOW:no-follow-ups'

async function scanTranscript(path) {
  let madeCommit = false
  let filedIssue = false
  let declaredNone = false

  const rl = readline.createInterface({
    input: fs.createReadStream(path, { encoding: 'utf8' }),
    crlfDelay: Infinity,
  })

  for await (const rawLine of rl) {
    const line = rawLine.trim()
    if (!line) continue
    let event
    try {
      event = JSON.parse(line)
    } catch {
      continue
    }
    if (!event || typeof event !== 'object' || event.type !== 'assistant') continue
    const message = event.message
    if (!message || typeof message !== 'object') continue
    const content = message.content
    if (!Array.isArray(content)) continue
    for (const block of content) {
      if (!block || typeof block !== 'object') continue
      if (block.type === 'tool_use' && block.name === 'Bash') {
        const command = block.input && block.input.command
        if (typeof command === 'string') {
          if (command.includes('git commit')) madeCommit = true
          if (command.includes('gh issue create')) filedIssue = true
        }
      } else if (block.type === 'text') {
        const text = block.text
        if (typeof text === 'string' && text.includes('WORKFLOW:no-follow-ups')) {
          declaredNone = true
        }
      }
    }
  }

  return { madeCommit, filedIssue, declaredNone }
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

  const transcriptPath = data && data.transcript_path
  if (!transcriptPath || typeof transcriptPath !== 'string') {
    process.exit(0)
  }
  if (!fs.existsSync(transcriptPath)) {
    process.exit(0)
  }

  const { madeCommit, filedIssue, declaredNone } = await scanTranscript(transcriptPath)

  if (madeCommit && !filedIssue && !declaredNone) {
    process.stdout.write(JSON.stringify({ decision: 'block', reason: BLOCK_REASON }) + '\n')
  }

  process.exit(0)
}

main().catch(() => {
  // Absolute last-resort guard: never let an unexpected error crash the Stop hook.
  process.exit(0)
})
