#!/usr/bin/env node
// PreToolUse pr-gate — dispatches on the `gh pr …` subcommand.
//
// `gh pr create` on a `feat/*` branch with NO spec/plan ADDED ON THE BRANCH (design-before-code,
// GATE 1) -> BLOCK. Bypass: WORKFLOW:no-design. Branch-scoped via a merge-base diff against trunk,
// NOT a repo-wide `git ls-files` (fix-round 1, CRITICAL-2 — a spec merged to trunk by an earlier PR
// must not silently satisfy every later branch forever).
//
// `gh pr merge` whose CI isn't green or whose PR isn't cleanly mergeable (merge-safety, P7) ->
// BLOCK. Bypass: WORKFLOW:force-merge. Fails OPEN whenever `gh` is offline/unauthenticated/
// unparseable.
//
// Detection is TOKEN-based, not a rigid `gh pr (create|merge)` regex — a global `gh` flag between
// the program and the subcommand (`gh --repo org/repo pr merge 123`, `gh -R org/repo pr create`)
// must not slip past detection (fix-round 1, CRITICAL-1). Any `--repo`/`-R`/`--hostname` flag found
// before `pr` is preserved and forwarded to the internal `gh pr view` lookup.
//
// Mirrors hooks/pr_gate.py exactly (parity asserted by tests/test_pr_gate.sh).

const { spawnSync } = require('node:child_process')

const SHELL_SEGMENT_SPLIT_RE = /&&|\|\||;|\n|\|/
const NO_DESIGN_BYPASS = 'WORKFLOW:no-design'
const FORCE_MERGE_BYPASS = 'WORKFLOW:force-merge'
const SPEC_PATHS = ['docs/superpowers/specs', 'docs/superpowers/plans']
const FEAT_BRANCH_RE = /^feat\//
const CI_FAILING_CONCLUSIONS = new Set([
  'FAILURE', 'CANCELLED', 'TIMED_OUT', 'ERROR', 'STARTUP_FAILURE', 'ACTION_REQUIRED',
])
const CI_NON_TERMINAL_STATES = new Set(['PENDING', 'QUEUED', 'IN_PROGRESS', 'REQUESTED', 'WAITING'])
const GH_VALUE_FLAGS = new Set(['-R', '--repo', '--hostname'])

// A minimal shlex-like tokenizer: splits on whitespace, honors single/double quotes. Good enough
// for the flag/subcommand shapes this gate needs to recognize (not a full shell parser).
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

function subcommandMatch(tokens, prog, path, valueFlags) {
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i] !== prog) continue
    let j = i + 1
    let prefixStart = j
    let prefixEnd = j
    let ok = true
    for (let pos = 0; pos < path.length; pos++) {
      j = skipFlags(tokens, j, valueFlags)
      if (pos === 0) prefixEnd = j
      if (j >= tokens.length || tokens[j] !== path[pos]) {
        ok = false
        break
      }
      j += 1
    }
    if (ok) return { prefixFlags: tokens.slice(prefixStart, prefixEnd), end: j }
  }
  return null
}

function run(cwd, args, timeout = 8000) {
  try {
    const r = spawnSync(args[0], args.slice(1), {
      cwd: cwd || undefined, encoding: 'utf8', timeout,
    })
    if (r.error || r.status !== 0) return null
    return r.stdout
  } catch {
    return null
  }
}

function currentBranch(cwd) {
  const out = run(cwd, ['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
  return out ? out.trim() : null
}

// Widened (fix-round 2, #142(b)) for repos whose trunk isn't main/master and have no origin/HEAD —
// see hooks/pr_gate.py's `_resolve_trunk` docstring for the full rationale (mirrors it exactly).
function resolveTrunk(cwd) {
  const ref = run(cwd, ['git', 'symbolic-ref', 'refs/remotes/origin/HEAD'])
  if (ref) {
    const parts = ref.trim().split('/')
    if (parts.length >= 2) return parts.slice(-2).join('/')
  }
  for (const candidate of ['origin/main', 'origin/master', 'main', 'master']) {
    if (run(cwd, ['git', 'rev-parse', '--verify', '--quiet', candidate]) !== null) return candidate
  }
  const upstreamRaw = run(cwd, ['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'])
  if (upstreamRaw && upstreamRaw.trim()) {
    const upstream = upstreamRaw.trim()
    // Reject a SELF push-upstream — see hooks/pr_gate.py's `_resolve_trunk` for the full
    // rationale (mirrors it exactly): `git push -u origin <branch>` sets @{u} to the branch's OWN
    // remote-tracking ref, not the trunk; using it false-CLOSES gh pr create for the single most
    // common git workflow (fix-round 2 CRITICAL).
    const branch = currentBranch(cwd)
    const upstreamTail = upstream.includes('/') ? upstream.split('/').slice(1).join('/') : upstream
    if (!branch || upstreamTail !== branch) return upstream
  }
  const defaultBranchRaw = run(cwd, ['git', 'config', 'init.defaultBranch'])
  if (defaultBranchRaw && defaultBranchRaw.trim()) {
    const defaultBranch = defaultBranchRaw.trim()
    for (const candidate of [`origin/${defaultBranch}`, defaultBranch]) {
      if (run(cwd, ['git', 'rev-parse', '--verify', '--quiet', candidate]) !== null) return candidate
    }
  }
  return null
}

function hasSpecOrPlan(cwd, branch) {
  const trunk = resolveTrunk(cwd)
  if (!trunk || trunk === branch) return true // can't determine a distinct trunk -> fail open
  const base = run(cwd, ['git', 'merge-base', 'HEAD', trunk])
  if (!base) return true // unrelated histories / can't compute -> fail open
  const out = run(cwd, ['git', 'diff', '--name-only', `${base.trim()}..HEAD`, '--', ...SPEC_PATHS])
  if (out === null) return true
  return out.split('\n').some((p) => p.trim())
}

function block(reason) {
  process.stdout.write(JSON.stringify({ decision: 'block', reason }) + '\n')
  process.exit(2)
}

function checkCreate(command, cwd) {
  if (command.includes(NO_DESIGN_BYPASS)) return
  const branch = currentBranch(cwd)
  if (!branch || !FEAT_BRANCH_RE.test(branch)) return
  if (hasSpecOrPlan(cwd, branch)) return
  block(
    `Blocked: \`gh pr create\` on '${branch}' with no design artifact ADDED ON THIS BRANCH — ` +
      'GATE 1 requires a spec (docs/superpowers/specs/**) or plan (docs/superpowers/plans/**) ' +
      "from brainstorming/writing-plans before a PR. For a genuinely trivial change, add " +
      `'${NO_DESIGN_BYPASS}' to the command.`
  )
}

// Collect every --repo/-R/--hostname flag(+value) ANYWHERE in `tokens`, not just before the
// matched subcommand — a flag placed AFTER `pr merge` is just as valid and must reach the internal
// `gh pr view` lookup (fix-round 2, MEDIUM). Mirrors hooks/pr_gate.py's `_collect_repo_flags`.
function collectRepoFlags(tokens, valueFlags) {
  const out = []
  let i = 0
  while (i < tokens.length) {
    const tok = tokens[i]
    if (valueFlags.has(tok)) {
      if (i + 1 < tokens.length) out.push(tok, tokens[i + 1])
      i += 2
    } else if ([...valueFlags].some((f) => tok.startsWith(f + '='))) {
      out.push(tok)
      i += 1
    } else {
      i += 1
    }
  }
  return out
}

function prJson(cwd, prefixFlags, tokens, end) {
  const args = ['gh', ...collectRepoFlags(tokens, GH_VALUE_FLAGS), 'pr', 'view']
  const j = skipFlags(tokens, end, GH_VALUE_FLAGS)
  if (j < tokens.length && !tokens[j].startsWith('-')) args.push(tokens[j])
  args.push('--json', 'statusCheckRollup,mergeable,baseRefName')
  const out = run(cwd, args)
  if (out === null) return null
  try {
    return JSON.parse(out)
  } catch {
    return null
  }
}

function ciOk(pr) {
  const rollup = pr.statusCheckRollup || []
  if (!rollup.length) return true
  for (const check of rollup) {
    const conclusion = (check.conclusion || '').toUpperCase()
    const state = (check.state || '').toUpperCase()
    if (CI_FAILING_CONCLUSIONS.has(conclusion) || CI_FAILING_CONCLUSIONS.has(state)) return false
    if (CI_NON_TERMINAL_STATES.has(state)) return false
    if (!conclusion && !state) return false
  }
  return true
}

function mergeableOk(pr) {
  const mergeable = (pr.mergeable || '').toUpperCase()
  return mergeable !== 'CONFLICTING'
}

function checkMerge(command, prefixFlags, tokens, end, cwd) {
  if (command.includes(FORCE_MERGE_BYPASS)) return
  const pr = prJson(cwd, prefixFlags, tokens, end)
  if (pr === null) return // gh offline/unauthenticated/unparseable -> fail open
  const ok1 = ciOk(pr)
  const ok2 = mergeableOk(pr)
  if (ok1 && ok2) return
  const reasons = []
  if (!ok1) reasons.push('CI checks are not all green')
  if (!ok2) reasons.push('the PR is not cleanly mergeable (conflicting with its base)')
  block(
    'Blocked: `gh pr merge` — ' + reasons.join(' and ') + '. Fix the underlying issue, or ' +
      `if this merge is genuinely safe, add '${FORCE_MERGE_BYPASS}' to the command.`
  )
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

  for (const segment of command.split(SHELL_SEGMENT_SPLIT_RE)) {
    const tokens = tokenize(segment)
    let m = subcommandMatch(tokens, 'gh', ['pr', 'create'], GH_VALUE_FLAGS)
    if (m !== null) {
      checkCreate(command, cwd)
      continue
    }
    m = subcommandMatch(tokens, 'gh', ['pr', 'merge'], GH_VALUE_FLAGS)
    if (m !== null) {
      checkMerge(command, m.prefixFlags, tokens, m.end, cwd)
    }
  }

  process.exit(0)
}

main().catch(() => {
  process.exit(0)
})
