#!/usr/bin/env node
// PreToolUse tdd-gate — V1 commit-time TDD enforcement (issue #150).
//
// Fires on a `git commit` (token-based, flag-tolerant — same segment-split/-C-resolution/-a
// staging pattern as grill_gate.cjs). Classifies every staged file as TEST / SOURCE / NEUTRAL and
// BLOCKs when the staged set has >=1 SOURCE change and 0 TEST changes. Bypass: WORKFLOW:no-tdd.
//
// SPLIT RESPONSIBILITIES (see docs/ENFORCEMENT.md): the test-driven-development skill teaches
// RED->GREEN and run-and-observe; a test RUNNER decides pass/fail; THIS gate only enforces that a
// test file changed ALONGSIDE a source change — it does NOT run tests and does NOT claim RED. See
// the V2->V4 roadmap in docs/ENFORCEMENT.md for stronger checks.
//
// CAVEAT: blocks a legitimate two-commit RED-then-GREEN split (impl-only "GREEN" commit has no
// test in ITS OWN staged set) — commit red+green together, or use the bypass for that commit.
//
// Fail-open: --amend, a merge commit (MERGE_HEAD present), not a git repo, no staged files, any
// git error. Overridable via TDD_GATE_TEST_GLOBS / TDD_GATE_SOURCE_GLOBS (comma-separated extra
// globs, env var or .claude/worktrees.conf). Mirrors hooks/tdd_gate.py exactly (parity asserted by
// tests/test_tdd_gate.sh).

const { spawnSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const SHELL_SEGMENT_SPLIT_RE = /&&|\|\||;|\n|\|/
const GIT_COMMIT_RE = /\bgit\s+commit\b/
const GIT_DASH_C_RE = /\bgit\s+-C\s+(\S+)/
const BYPASS_SENTINEL = 'WORKFLOW:no-tdd'
const COMMIT_ALL_LONG = '--all'
const ADD_STAGES_EVERYTHING_FLAGS = new Set(['-A', '--all', '-u', '--update'])

// A pattern anchored to the START of the string (no leading `*`) only matches a TOP-LEVEL dir of
// that name — "tests/*" does NOT match a NESTED "myapp/tests/test_x.py" (Django's own per-app
// convention); needs a leading `*/` variant too (fix-round, adversarial audit CRITICAL — mirrors
// hooks/tdd_gate.py's widening exactly: nested tests/, Ruby spec/ + _spec.rb, JS/TS __tests__/).
// `*_spec.rb` is extension-SCOPED (not a bare "*_spec.*") — a bare wildcard extension over-matched
// non-test files merely ending in "_spec" (e.g. api_spec.json), a false-negative letting a
// source-only commit slip through (fix-round 2, adversarial re-check). Dotted `.spec.js`/`.spec.ts`
// forms are already covered by `*.spec.*` above.
//
// DIRECTORY-NAME globs classify EVERY file under that dir as TEST regardless of extension/content —
// safe ONLY for a strongly test-exclusive dir name. "spec/"/"*/spec/*" were DROPPED (fix-round 3,
// adversarial re-audit): "spec" is a heavily overloaded word (OpenAPI/Swagger spec docs, schema
// dirs, design-spec docs all commonly live under "spec/") — TEST is checked BEFORE NEUTRAL, so a
// plain `spec/openapi.yaml` was wrongly swept into TEST purely by directory name. `*_spec.rb` alone
// already fully covers RSpec regardless of directory (fnmatch's `*` crosses `/`), so dropping the
// dir globs loses zero real coverage. "test"/"tests"/"__tests__" are near-universally test-code
// directory names (no comparable "specification" collision), so those stay as directory globs.
const TEST_GLOBS_DEFAULT = [
  '*.test.*', '*.spec.*', '*_test.*', '*_spec.rb', 'test_*.py',
  'tests/*', '*/tests/*', 'test/*', '*/test/*',
  '__tests__/*', '*/__tests__/*',
  'e2e/*', '*.spec.ts',
]
const NEUTRAL_GLOBS_DEFAULT = [
  '*.md', '*.json', '*.yml', '*.yaml', '*.toml', '*.lock', '*.cfg', '*.ini',
  '*.css', '*.scss', '*.png', '*.jpg', '*.jpeg', '*.gif', '*.svg', '*.ico', 'docs/*',
]
const SOURCE_EXTS_DEFAULT = new Set([
  '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.py', '.go', '.rs', '.java',
  '.rb', '.php', '.c', '.cpp', '.h', '.hpp', '.sh',
])

// Minimal shlex-like tokenizer: whitespace-split, honors single/double quotes.
function shlexSplit(s) {
  const tokens = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let m
  while ((m = re.exec(s)) !== null) {
    tokens.push(m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3])
  }
  return tokens
}

// fnmatch-style glob: `*` matches anything including `/` (mirrors Python's fnmatch semantics used
// by tdd_gate.py, NOT shell globbing which stops at `/`).
function fnmatch(str, pattern) {
  const esc = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&')
  const re = new RegExp('^' + esc.replace(/\*/g, '.*').replace(/\?/g, '.') + '$')
  return re.test(str)
}

function run(cwd, args, timeout = 5000) {
  try {
    const r = spawnSync(args[0], args.slice(1), { cwd: cwd || undefined, encoding: 'utf8', timeout })
    if (r.error || r.status !== 0) return null
    return r.stdout
  } catch {
    return null
  }
}

function resolveGitCwd(segment, cwd) {
  const m = GIT_DASH_C_RE.exec(segment)
  if (!m) return cwd
  const target = m[1].replace(/^['"]|['"]$/g, '')
  return path.isAbsolute(target) ? target : path.join(cwd || '.', target)
}

function stagedNames(cwd) {
  const out = run(cwd, ['git', 'diff', '--cached', '--name-only'])
  return out ? out.split('\n').map((p) => p.trim()).filter(Boolean) : []
}

function addSegmentStagesEverything(segment) {
  const m = /\bgit\s+add\b(.*)$/.exec(segment)
  if (!m) return false
  const tokens = shlexSplit(m[1])
  if (tokens.some((t) => ADD_STAGES_EVERYTHING_FLAGS.has(t))) return true
  return tokens.some((t) => !t.startsWith('-') && (t === '.' || t === './'))
}

function explicitAddPaths(segment) {
  const m = /\bgit\s+add\b(.*)$/.exec(segment)
  if (!m) return []
  return shlexSplit(m[1]).filter((t) => t && !t.startsWith('-'))
}

function wouldBeStagedEverything(cwd) {
  const out = run(cwd, ['git', 'status', '--porcelain', '--untracked-files=all'])
  if (!out) return []
  const paths = []
  for (const line of out.split('\n')) {
    if (line.length < 4) continue
    let rest = line.slice(3).trim()
    if (rest.includes(' -> ')) rest = rest.split(' -> ')[1].trim()
    if (rest.length >= 2 && rest[0] === '"' && rest[rest.length - 1] === '"') {
      rest = rest.slice(1, -1)
    }
    if (rest) paths.push(rest)
  }
  return paths
}

function collectStaged(command, cwd) {
  const paths = stagedNames(cwd)
  for (const segment of command.split(SHELL_SEGMENT_SPLIT_RE)) {
    if (!/\bgit\s+add\b/.test(segment)) continue
    if (addSegmentStagesEverything(segment)) paths.push(...wouldBeStagedEverything(cwd))
    else paths.push(...explicitAddPaths(segment))
  }
  return paths
}

function commitSegment(command) {
  return command.split(SHELL_SEGMENT_SPLIT_RE).find((s) => GIT_COMMIT_RE.test(s)) || command
}

function commitTokens(segment) {
  const m = /\bcommit\b(.*)$/.exec(segment)
  if (!m) return []
  return shlexSplit(m[1])
}

function commitStagesAll(command) {
  const tokens = commitTokens(commitSegment(command))
  for (const t of tokens) {
    if (t === COMMIT_ALL_LONG) return true
    if (t.startsWith('--')) continue
    if (t.startsWith('-') && t.length > 1) {
      for (const ch of t.slice(1)) {
        if (ch === 'a') return true
        if (ch === 'm') break
      }
    }
  }
  return false
}

function commitIsAmend(command) {
  return commitTokens(commitSegment(command)).includes('--amend')
}

function modifiedTracked(cwd) {
  const out = run(cwd, ['git', 'diff', '--name-only'])
  return out ? out.split('\n').map((p) => p.trim()).filter(Boolean) : []
}

function isMergeInProgress(cwd) {
  return run(cwd, ['git', 'rev-parse', '-q', '--verify', 'MERGE_HEAD']) !== null
}

function extraGlobs(cwd, envName, confKey) {
  let val = process.env[envName]
  if (val === undefined) {
    const confPath = path.join(cwd || '.', '.claude', 'worktrees.conf')
    let text = ''
    try {
      text = fs.readFileSync(confPath, 'utf8')
    } catch {
      text = ''
    }
    const re = new RegExp(`^${confKey.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*=\\s*"?([^"\\n]*)"?`, 'm')
    const m = re.exec(text)
    val = m ? m[1] : ''
  }
  return val.split(',').map((g) => g.trim()).filter(Boolean)
}

function classify(p, testGlobs, sourceGlobs) {
  const norm = p.replace(/\\/g, '/')
  if (
    TEST_GLOBS_DEFAULT.some((g) => fnmatch(norm, g)) ||
    testGlobs.some((g) => fnmatch(norm, g))
  ) {
    return 'TEST'
  }
  if (NEUTRAL_GLOBS_DEFAULT.some((g) => fnmatch(norm, g))) return 'NEUTRAL'
  if (sourceGlobs.some((g) => fnmatch(norm, g))) return 'SOURCE'
  const ext = path.extname(norm)
  if (SOURCE_EXTS_DEFAULT.has(ext)) return 'SOURCE'
  return 'NEUTRAL'
}

function block(reason) {
  process.stdout.write(JSON.stringify({ decision: 'block', reason }) + '\n')
  process.exit(2)
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

  if ((data && data.tool_name) !== 'Bash') process.exit(0)
  const command = (data.tool_input && data.tool_input.command) || ''
  const cwd = data.cwd || ''

  if (!GIT_COMMIT_RE.test(command)) process.exit(0)
  if (command.includes(BYPASS_SENTINEL)) process.exit(0)
  if (commitIsAmend(command)) process.exit(0)

  const seg = commitSegment(command)
  const gitCwd = resolveGitCwd(seg, cwd)
  if (isMergeInProgress(gitCwd)) process.exit(0)

  const stagesAll = commitStagesAll(command)
  let paths = collectStaged(command, gitCwd)
  if (stagesAll) paths = paths.concat(modifiedTracked(gitCwd))

  const uniquePaths = [...new Set(paths)]
  if (uniquePaths.length === 0) process.exit(0) // nothing staged (incl. not-a-git-repo) -> fail open

  const testGlobs = extraGlobs(gitCwd, 'TDD_GATE_TEST_GLOBS', 'TDD_GATE_TEST_GLOBS')
  const sourceGlobs = extraGlobs(gitCwd, 'TDD_GATE_SOURCE_GLOBS', 'TDD_GATE_SOURCE_GLOBS')
  const classes = uniquePaths.map((p) => classify(p, testGlobs, sourceGlobs))
  const hasSource = classes.includes('SOURCE')
  const hasTest = classes.includes('TEST')

  if (hasSource && !hasTest) {
    const sourceFiles = uniquePaths.filter((_, i) => classes[i] === 'SOURCE')
    block(
      'Blocked: implementation changed with no accompanying test change (#TDD) — ' +
        `staged source file(s): ${sourceFiles.slice(0, 5).join(', ')}` +
        `${sourceFiles.length > 5 ? '…' : ''}. Write/adjust a test, or add ` +
        `'${BYPASS_SENTINEL}' to the commit command.`
    )
  }

  process.exit(0)
}

main().catch(() => {
  process.exit(0)
})
