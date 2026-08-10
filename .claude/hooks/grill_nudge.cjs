#!/usr/bin/env node
// PostToolUse grill-nudge — non-blocking WARN when a plan file is written/edited without a
// non-empty `## Grill findings` section.
//
// A hook cannot literally invoke `grill-me` (deterministic guard, not a skill-runner) — so "every
// plan auto-triggers a pressure-test" (rules/workflow-adherence.md #5) is nudge + existing block,
// not literal auto-invocation.
//
// Covers BOTH docs/superpowers/plans/**/*.md (already BLOCKED at `git commit` time by
// grill_gate.py/.cjs) AND the plan-mode path ~/.claude/plans/*.md (outside grill_gate's reach — it
// lives outside any project git repo, never appears in `git diff --cached`; this nudge, firing on
// the Write/Edit itself, is the only mechanism that can observe it).
//
// Never blocks. Fail-open on any error. Mirrors hooks/grill_nudge.py exactly (parity asserted by
// tests/test_grill_nudge.sh).

const fs = require('node:fs')
const path = require('node:path')

const PLAN_PATH_RE = /(^|[/\\])docs[/\\]superpowers[/\\]plans[/\\][^/\\]+\.md$/
const PLAN_MODE_PATH_RE = /(^|[/\\])\.claude[/\\]plans[/\\][^/\\]+\.md$/

// #148: tolerate trailing text on the heading line (mirrors grill_gate.py's widening exactly).
const GRILL_HEADER_RE = /^\s*##\s+Grill findings\b.*$/m
const DISPOSITION_RE =
  /\b(fixed|parked|deferred|accepted|resolved|mitigated|addressed|acknowledged|wontfix|won'?t\s*fix|noted|ruled)\b/i
const FINDING_BULLET_RE = /^\s*[-*]\s*C\d+\b/
const CONTENT_BULLET_RE = /^\s*[-*]\s+\S/

const NOTICE =
  "Notice: this plan has no non-empty '## Grill findings' section yet. " +
  'rules/workflow-adherence.md #5 requires grilling the PLAN (not just the design) before BUILD ' +
  "— run grill-me and record findings + dispositions. This never blocks; it's a reminder."

function isTableSeparator(s) {
  if (!s || !s.startsWith('|')) return false
  if (!/^[|\- :]*$/.test(s)) return false
  return s.includes('-')
}

function tableCells(s) {
  return s
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())
}

function isRealFinding(s) {
  return DISPOSITION_RE.test(s) || FINDING_BULLET_RE.test(s) || CONTENT_BULLET_RE.test(s)
}

function hasNonemptyGrillSection(text) {
  const m = GRILL_HEADER_RE.exec(text)
  if (!m) return false
  const after = text.slice(m.index + m[0].length)
  const nxt = /^\s*##\s+/m.exec(after)
  const body = nxt ? after.slice(0, nxt.index) : after
  for (const raw of body.split('\n')) {
    const s = raw.trim()
    if (!s) continue
    if (s.startsWith('>')) continue
    if (isTableSeparator(s)) continue
    if (s.startsWith('|')) {
      const cells = tableCells(s)
      if (cells.every((c) => c === '')) continue
      if (isRealFinding(cells.join(' '))) return true
      continue
    }
    if (isRealFinding(s)) return true
  }
  return false
}

function isWatchedPlan(p) {
  if (typeof p !== 'string' || !p) return false
  if (path.basename(p).toUpperCase().startsWith('TEMPLATE')) return false
  return PLAN_PATH_RE.test(p) || PLAN_MODE_PATH_RE.test(p)
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

  const toolName = data && data.tool_name
  if (toolName !== 'Write' && toolName !== 'Edit') process.exit(0)

  const filePath = data.tool_input && data.tool_input.file_path
  if (!isWatchedPlan(filePath)) process.exit(0)

  let text
  try {
    text = fs.readFileSync(filePath, 'utf8')
  } catch {
    process.exit(0) // missing/unreadable -> fail open
  }

  if (hasNonemptyGrillSection(text)) process.exit(0)

  process.stdout.write(JSON.stringify({ systemMessage: NOTICE }) + '\n')
  process.exit(0)
}

main().catch(() => {
  process.exit(0)
})
