#!/usr/bin/env node
// Stop hook — CLOSE-phase workflow gate (P8), sibling to the proven close_issue_gate.cjs.
//
// Scans the session transcript (JSONL) for tool-events + assistant text, then enforces/nudges
// THREE distinct P8 CLOSE commitments:
//   - reflect BLOCK  — gh pr merge seen but no /dev-reflect (or docs(lessons): commit) -> block.
//     Bypass: WORKFLOW:no-reflect.
//   - handoff WARN   — gh pr merge seen but primary worktree's HANDOFF.md wasn't touched this
//     session (fuzzy, mtime-only) -> non-blocking notice. No bypass.
//   - verify WARN    — git commit seen but no test/lint/validate run detected -> non-blocking
//     notice. Bypass: WORKFLOW:no-verify.
//
// Mirrors close_gate.py exactly (parity is asserted by tests/test_close_gate.sh). Never crashes:
// any exception, missing/unreadable transcript, or malformed JSON silently exits 0.
// close_issue_gate.cjs is left UNTOUCHED (proven sibling, own behavior tests).
//
// Non-blocking notices use the same `systemMessage` JSON field skill_nudge.cjs already
// established for a non-SessionStart hook — never a `decision` field, so Stop is never blocked
// by a WARN-tier finding.
//
// Detection of `git commit` and `gh pr merge` inside a transcript Bash command is TOKEN-based, not
// a plain substring check — `git -C <path> commit ...` and `gh --repo org/repo pr merge ...` /
// `gh -R ... pr merge ...` both defeated a naive `.includes(...)` check (fix-round 1, CRITICAL-1 +
// HIGH).
//
// Known limitation (documented, not fixed here — see docs/ENFORCEMENT.md): this scanner only sees
// Bash/Skill tool_use blocks the CURRENT session's own transcript recorded directly. A merge or
// /dev-reflect performed by a delegated subagent/teammate, or erased by mid-session compaction, is
// structurally invisible to it.

const fs = require('node:fs')
const { spawnSync } = require('node:child_process')

const SHELL_SEGMENT_SPLIT_RE = /&&|\|\||;|\n|\|/
const GIT_VALUE_FLAGS = new Set(['-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path'])
const GH_VALUE_FLAGS = new Set(['-R', '--repo', '--hostname'])

// A minimal shlex-like tokenizer: splits on whitespace, honors single/double quotes.
function tokenize(segment) {
  const tokens = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let m
  while ((m = re.exec(segment)) !== null) {
    tokens.push(m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3])
  }
  return tokens
}

function skipFlags(tokens, i, valueFlags) {
  while (i < tokens.length && tokens[i].startsWith('-') && tokens[i] !== '-') {
    const tok = tokens[i]
    if (tok.includes('=')) {
      i += 1
    } else if (valueFlags.has(tok)) {
      i += 2
    } else {
      i += 1
    }
  }
  return i
}

function hasSubcommand(command, prog, path, valueFlags) {
  for (const segment of command.split(SHELL_SEGMENT_SPLIT_RE)) {
    const tokens = tokenize(segment)
    for (let i = 0; i < tokens.length; i++) {
      if (tokens[i] !== prog) continue
      let j = i + 1
      let ok = true
      for (const expected of path) {
        j = skipFlags(tokens, j, valueFlags)
        if (j >= tokens.length || tokens[j] !== expected) {
          ok = false
          break
        }
        j += 1
      }
      if (ok) return true
    }
  }
  return false
}

const REFLECT_BLOCK_REASON =
  'CLOSE gate ⛔ — this session merged a PR but never ran /dev-reflect (no ' +
  '`docs(lessons):` commit or dev-reflect invocation detected). Harvest wins + lessons ' +
  "into the project's lessons file before stopping, or state exactly: WORKFLOW:no-reflect"

const HANDOFF_WARN =
  "CLOSE notice: this session merged a PR but the primary worktree's HANDOFF.md doesn't " +
  'look like it was updated this session — run /handoff for session continuity.'

const VERIFY_WARN =
  'CLOSE notice: this session committed changes but no test/lint/validate run was ' +
  "detected — GATE-2 wants fresh evidence before 'done' (run /validate). If verification " +
  'genuinely does not apply, state: WORKFLOW:no-verify'

const NO_REFLECT_BYPASS = 'WORKFLOW:no-reflect'
const NO_VERIFY_BYPASS = 'WORKFLOW:no-verify'

const TEST_RUNNER_RE =
  /\b(pytest|npm\s+test|vitest|cargo\s+test|go\s+test|bash\s+tests\/run\.sh|cc-worktrees\s+test|npm\s+run\s+lint|ruff\s+check)\b/
const REFLECT_MARKER_RE = /dev-reflect|docs\(lessons\):/

function run(args, cwd, timeout = 5000) {
  try {
    const r = spawnSync(args[0], args.slice(1), { cwd: cwd || undefined, encoding: 'utf8', timeout })
    if (r.error || r.status !== 0) return null
    return r.stdout
  } catch {
    return null
  }
}

function primaryWorktree(cwd) {
  const out = run(['git', 'worktree', 'list', '--porcelain'], cwd)
  if (out === null) return null
  for (const line of out.split('\n')) {
    if (line.startsWith('worktree ')) return line.slice('worktree '.length).trim()
  }
  return null
}

function parseTs(raw) {
  if (typeof raw !== 'string' || !raw) return null
  const d = new Date(raw)
  return Number.isNaN(d.getTime()) ? null : d
}

function scanTranscript(path) {
  let madeCommit = false
  let didMerge = false
  let ranReflect = false
  let ranTest = false
  let noReflect = false
  let noVerify = false
  let firstTs = null

  const text = fs.readFileSync(path, 'utf8')
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (!line) continue
    let event
    try {
      event = JSON.parse(line)
    } catch {
      continue
    }
    if (!event || typeof event !== 'object') continue
    if (firstTs === null) {
      const ts = parseTs(event.timestamp)
      if (ts !== null) firstTs = ts
    }
    if (event.type !== 'assistant') continue
    const message = event.message
    if (!message || typeof message !== 'object') continue
    const content = message.content
    if (!Array.isArray(content)) continue
    for (const block of content) {
      if (!block || typeof block !== 'object') continue
      const btype = block.type
      if (btype === 'tool_use' && block.name === 'Bash') {
        const command = (block.input && block.input.command) || ''
        if (typeof command === 'string') {
          if (hasSubcommand(command, 'git', ['commit'], GIT_VALUE_FLAGS)) madeCommit = true
          if (hasSubcommand(command, 'gh', ['pr', 'merge'], GH_VALUE_FLAGS)) didMerge = true
          if (REFLECT_MARKER_RE.test(command)) ranReflect = true
          if (TEST_RUNNER_RE.test(command)) ranTest = true
        }
      } else if (btype === 'tool_use' && block.name === 'Skill') {
        const skill = JSON.stringify(block.input || {})
        if (skill.includes('dev-reflect')) ranReflect = true
      } else if (btype === 'text') {
        const t = block.text || ''
        if (typeof t === 'string') {
          if (REFLECT_MARKER_RE.test(t)) ranReflect = true
          if (t.includes(NO_REFLECT_BYPASS)) noReflect = true
          if (t.includes(NO_VERIFY_BYPASS)) noVerify = true
        }
      }
    }
  }
  return { madeCommit, didMerge, ranReflect, ranTest, noReflect, noVerify, firstTs }
}

function handoffStale(cwd, firstTs) {
  if (firstTs === null) return false
  const primary = primaryWorktree(cwd)
  if (!primary) return false
  const handoff = `${primary}/HANDOFF.md`
  let mtimeMs
  try {
    mtimeMs = fs.statSync(handoff).mtimeMs
  } catch {
    return true // HANDOFF.md doesn't exist -> stale
  }
  return mtimeMs < firstTs.getTime()
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
  if (!transcriptPath || typeof transcriptPath !== 'string') process.exit(0)
  const cwd = data.cwd || ''

  let scanned
  try {
    scanned = scanTranscript(transcriptPath)
  } catch {
    process.exit(0)
  }

  const { madeCommit, didMerge, ranReflect, ranTest, noReflect, noVerify, firstTs } = scanned

  if (didMerge && !ranReflect && !noReflect) {
    process.stdout.write(JSON.stringify({ decision: 'block', reason: REFLECT_BLOCK_REASON }) + '\n')
    process.exit(0)
  }

  const notices = []
  if (didMerge && handoffStale(cwd, firstTs)) notices.push(HANDOFF_WARN)
  if (madeCommit && !ranTest && !noVerify) notices.push(VERIFY_WARN)
  if (notices.length) {
    process.stdout.write(JSON.stringify({ systemMessage: notices.join('\n') }) + '\n')
  }

  process.exit(0)
}

main().catch(() => {
  process.exit(0)
})
