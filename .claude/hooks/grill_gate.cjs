#!/usr/bin/env node
// PreToolUse grill-gate — blocks committing a spec/plan/ADR with no non-empty `## Grill findings`
// section. Bypass: WORKFLOW:no-grill. Fail-open on any error.
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

// issue #116 — docs/superpowers/plans/** is watched too: a plan is a second GATE-1 artifact that
// must be grilled post-writing-plans, same mechanism as the spec/ADR check.
//
// NOTE (#146-T3): this hook does NOT (and structurally cannot) cover the plan-mode path
// (~/.claude/plans/*.md) — it lives outside any project's git repo, so it can never appear in
// `git diff --cached` for a project commit. grill_nudge.py/.cjs (PostToolUse, WARN-only) covers
// that path instead, firing on the Write/Edit itself.
const SPEC_PREFIXES = ['docs/superpowers/specs/', 'docs/superpowers/plans/', 'docs/decisions/']
const GIT_COMMIT_RE = /\bgit\s+commit\b/
const GIT_DASH_C_RE = /\bgit\s+-C\s+(\S+)/
const SHELL_SEGMENT_SPLIT_RE = /&&|\|\||;|\n|\|/
const GIT_ADD_RE = /\bgit\s+add\b/
const ADD_STAGES_EVERYTHING_FLAGS = ['-A', '--all', '-u', '--update']
const COMMIT_ALL_LONG = '--all'
const BYPASS_SENTINEL = 'WORKFLOW:no-grill'
// #148: tolerate trailing text on the heading line (e.g. an annotation) — mirrors grill_gate.py.
const GRILL_HEADER_RE = /^\s*##\s+Grill findings\b.*$/m
// A "real finding" line records a disposition, is a `- C1 —` finding bullet, or (issue #108) is ANY
// content bullet (`- <text>` / `* <text>`) — so a grill written as prose bullets ALLOWs instead of
// false-blocking. The disposition vocabulary is widened past fixed/parked/deferred/accepted to the
// words real grills actually use. A copied TEMPLATE with an UNFILLED table still BLOCKS: its skeleton
// has NO content bullets (only the blockquote, the header row, the `|---|` separator, an empty row).
const DISPOSITION_RE =
  /\b(fixed|parked|deferred|accepted|resolved|mitigated|addressed|acknowledged|wontfix|won't\s*fix|noted|ruled)\b/i
const FINDING_BULLET_RE = /^\s*[-*]\s*C\d+\b/
// Any bullet with real content after the marker — the general widening for prose-style grills.
const CONTENT_BULLET_RE = /^\s*[-*]\s+\S/

function resolveGitCwd(segment, cwd) {
  const m = GIT_DASH_C_RE.exec(segment)
  if (!m) return cwd
  const t = m[1].replace(/^['"]|['"]$/g, '')
  return path.isAbsolute(t) ? t : path.join(cwd || '.', t)
}
function runGit(cwd, args) {
  try {
    return execFileSync('git', args, {
      cwd: cwd || undefined, encoding: 'utf8', timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
  } catch {
    return null
  }
}
function stagedNames(cwd) {
  const out = runGit(cwd, ['diff', '--cached', '--name-only'])
  return out ? out.split('\n').map((p) => p.trim()).filter(Boolean) : []
}
function tokenize(rest) {
  const tokens = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let m
  while ((m = re.exec(rest)) !== null) tokens.push(m[1] ?? m[2] ?? m[3])
  return tokens
}
function addSegmentStagesEverything(segment) {
  const m = segment.match(/\bgit\s+add\b(.*)$/)
  if (!m) return false
  const tokens = tokenize(m[1])
  if (tokens.some((t) => ADD_STAGES_EVERYTHING_FLAGS.includes(t))) return true
  return tokens.filter((t) => t && !t.startsWith('-')).some((p) => p === '.' || p === './')
}
function explicitAddPaths(segment) {
  const m = segment.match(/\bgit\s+add\b(.*)$/)
  if (!m) return []
  return tokenize(m[1]).filter((t) => t && !t.startsWith('-'))
}
function wouldBeStagedEverything(cwd) {
  const out = runGit(cwd, ['status', '--porcelain', '--untracked-files=all'])
  if (!out) return []
  const paths = []
  for (const line of out.split('\n')) {
    if (line.length < 4) continue
    let rest = line.slice(3).trim()
    if (rest.includes(' -> ')) rest = rest.split(' -> ')[1].trim()
    if (rest.length >= 2 && rest[0] === '"' && rest[rest.length - 1] === '"') rest = rest.slice(1, -1)
    if (rest) paths.push(rest)
  }
  return paths
}
function collectStaged(command, cwd) {
  const paths = stagedNames(cwd)
  for (const segment of command.split(SHELL_SEGMENT_SPLIT_RE)) {
    if (!GIT_ADD_RE.test(segment)) continue
    if (addSegmentStagesEverything(segment)) paths.push(...wouldBeStagedEverything(cwd))
    else paths.push(...explicitAddPaths(segment))
  }
  return paths
}
function isSpecPath(p) {
  const norm = p.replace(/^[./]+/, '') // W2: parity with py `path.lstrip("./")`
  if (!SPEC_PREFIXES.some((pre) => norm.startsWith(pre))) return false
  const base = norm.split('/').pop()
  return !base.toUpperCase().startsWith('TEMPLATE')
}
function commitStagesAll(command) {
  // True if the `git commit` command auto-stages modified tracked files (-a / --all / -am).
  const seg = command.split(SHELL_SEGMENT_SPLIT_RE).find((s) => GIT_COMMIT_RE.test(s)) || command
  const m = seg.match(/\bcommit\b(.*)$/)
  if (!m) return false
  for (const t of tokenize(m[1])) {
    if (t === COMMIT_ALL_LONG) return true
    if (t.startsWith('--')) continue
    if (t.startsWith('-') && t.length > 1) {
      for (const ch of t.slice(1)) {
        if (ch === 'a') return true
        if (ch === 'm') break // -m consumes the remainder of the cluster as the message
      }
    }
  }
  return false
}
function modifiedTracked(cwd) {
  // Tracked files with unstaged modifications — what a `git commit -a` would additionally stage.
  const out = runGit(cwd, ['diff', '--name-only'])
  return out ? out.split('\n').map((p) => p.trim()).filter(Boolean) : []
}
function fileText(cwd, p, preferWorktree) {
  // Normal commits use the STAGED blob; a `git commit -a` stages the WORKTREE version, so for that
  // path the worktree file wins over the stale index blob.
  const worktree = () => {
    const full = path.isAbsolute(p) ? p : path.join(cwd || '.', p)
    try {
      return fs.readFileSync(full, 'utf8')
    } catch {
      return null
    }
  }
  const staged = () => runGit(cwd, ['show', `:${p}`])
  if (preferWorktree) {
    const t = worktree()
    return t !== null ? t : staged()
  }
  const t = staged()
  return t !== null ? t : worktree()
}
function isTableSeparator(s) {
  return !!s && s.startsWith('|') && [...s].every((c) => '|-: '.includes(c)) && s.includes('-')
}
function tableCells(s) {
  return s.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
}
function isRealFinding(s) {
  return DISPOSITION_RE.test(s) || FINDING_BULLET_RE.test(s) || CONTENT_BULLET_RE.test(s)
}
function hasNonemptyGrillSection(text) {
  // A FILLED grill section — not just the TEMPLATE skeleton. Excludes the instruction blockquote,
  // the markdown table HEADER row (the row directly above a `|---|` separator), the separator
  // itself, and empty-cell rows. Requires at least one remaining line recording a real finding +
  // disposition. A copied TEMPLATE whose table is unfilled therefore BLOCKS.
  const m = GRILL_HEADER_RE.exec(text)
  if (!m) return false
  const after = text.slice(m.index + m[0].length)
  const nxt = /^\s*##\s+/m.exec(after)
  const body = nxt ? after.slice(0, nxt.index) : after
  const lines = body.split('\n')
  const n = lines.length
  for (let i = 0; i < n; i++) {
    const s = lines[i].trim()
    if (!s) continue
    if (s.startsWith('>')) continue // instruction blockquote — not content
    if (isTableSeparator(s)) continue // |---| separator — not content
    if (s.startsWith('|')) {
      const cells = tableCells(s)
      if (cells.every((c) => c === '')) continue // empty-cell data row — not content
      let j = i + 1
      while (j < n && !lines[j].trim()) j++
      if (j < n && isTableSeparator(lines[j].trim())) continue // column-header row — not content
      if (isRealFinding(cells.join(' '))) return true
      continue
    }
    if (isRealFinding(s)) return true // a prose / bullet finding line
  }
  return false
}

let raw = ''
process.stdin.on('data', (d) => (raw += d))
process.stdin.on('end', () => {
  let data = {}
  try {
    data = JSON.parse(raw || '{}')
  } catch {
    process.exit(0)
  }
  if ((data.tool_name || '') !== 'Bash') process.exit(0)
  const command = (data.tool_input || {}).command || ''
  const cwd = data.cwd || ''
  const block = (reason) => {
    console.log(JSON.stringify({ decision: 'block', reason }))
    process.exit(2)
  }
  try {
    if (!GIT_COMMIT_RE.test(command)) process.exit(0)
    if (command.includes(BYPASS_SENTINEL)) process.exit(0)
    const commitSeg =
      command.split(SHELL_SEGMENT_SPLIT_RE).find((s) => GIT_COMMIT_RE.test(s)) || command
    const gitCwd = resolveGitCwd(commitSeg, cwd)
    const stagesAll = commitStagesAll(command)
    const paths = collectStaged(command, gitCwd)
    if (stagesAll) paths.push(...modifiedTracked(gitCwd))
    const seen = new Set()
    for (const p of paths) {
      if (seen.has(p)) continue
      seen.add(p)
      if (!isSpecPath(p)) continue
      // `git commit -a` will stage the WORKTREE version → read that, not the stale index blob.
      const text = fileText(gitCwd, p, stagesAll)
      if (text === null) continue
      if (!hasNonemptyGrillSection(text)) {
        block(
          `Blocked: '${p}' is a spec/plan/ADR with no non-empty '## Grill findings' section. Run ` +
            'grill-me and record findings + dispositions (see rules/workflow-adherence.md). For ' +
            `a genuinely trivial doc, add '${BYPASS_SENTINEL}' to the commit command — but ` +
            'prefer recording the grill.',
        )
      }
    }
  } catch {
    process.exit(0)
  }
  process.exit(0)
})
