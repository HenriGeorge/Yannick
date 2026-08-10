#!/usr/bin/env node
// SessionStart hook (Node) — print git status + GATE-0 behind-count (H4) into the session context.
// SessionStart is INJECT-ONLY (researcher §4) — it can never block, so every path here exits 0 and
// never throws uncaught. Best-effort `git fetch` (short timeout, fails SILENTLY offline), then
// compute the local branch's behind-count vs the default remote branch. Gracefully skips (no
// crash) when: not a git repo, detached HEAD / no branch, no `origin` remote, or fetch/rev-list
// itself fails.
const { execFileSync } = require('node:child_process')
const path = require('node:path')

function run(args, cwd, timeoutMs = 5000) {
  // Never throws — returns null on any failure (missing git, timeout, non-zero exit, etc.)
  try {
    const out = execFileSync('git', args, { cwd, encoding: 'utf8', timeout: timeoutMs, stdio: ['ignore', 'pipe', 'ignore'] })
    return { ok: true, stdout: out }
  } catch {
    return { ok: false, stdout: '' }
  }
}

function defaultBranch(dir) {
  const ref = run(['symbolic-ref', 'refs/remotes/origin/HEAD'], dir)
  if (ref.ok && ref.stdout.trim()) {
    const parts = ref.stdout.trim().split('/')
    return parts[parts.length - 1]
  }
  for (const candidate of ['main', 'master']) {
    const check = run(['rev-parse', '--verify', '--quiet', `origin/${candidate}`], dir)
    if (check.ok) return candidate
  }
  return null
}

function gate0Line(dir) {
  const inside = run(['rev-parse', '--is-inside-work-tree'], dir, 3000)
  if (!inside.ok || inside.stdout.trim() !== 'true') return null // not a git repo — H4.5

  const branchR = run(['branch', '--show-current'], dir, 3000)
  const branch = branchR.ok ? branchR.stdout.trim() : ''
  if (!branch) return 'GATE-0: detached HEAD or no current branch — skipping behind-count.' // H4.3

  const remoteR = run(['remote', 'get-url', 'origin'], dir, 3000)
  if (!remoteR.ok || !remoteR.stdout.trim()) {
    return 'GATE-0: no origin remote configured — skipping behind-count.' // H4.3
  }

  const fetchR = run(['fetch', '--quiet', 'origin'], dir, 8000)
  const fetchOk = fetchR.ok // H4.4 fail-open on offline/timeout

  const defBranch = defaultBranch(dir)
  if (!defBranch) return 'GATE-0: no origin default branch found — skipping behind-count.'

  const ref = `origin/${defBranch}`
  const exists = run(['rev-parse', '--verify', '--quiet', ref], dir, 3000)
  if (!exists.ok) {
    const note = fetchOk ? '' : ' (git fetch failed — offline?)'
    return `GATE-0: no ${ref} ref available${note} — skipping behind-count.`
  }

  const countR = run(['rev-list', '--count', `HEAD..${ref}`], dir, 3000)
  if (!countR.ok) return null // can't compute — skip silently rather than guess

  const n = parseInt(countR.stdout.trim() || '0', 10)
  if (Number.isNaN(n)) return null

  const suffix = fetchOk ? '' : ' (git fetch failed — count may be stale)'
  if (n > 0) {
    return `⚠ GATE-0: you are ${n} commit(s) behind ${defBranch}${suffix} — rebase before building (docs/WORKFLOW.md Phase 0).`
  }
  return `✓ GATE-0: up to date with ${defBranch}${suffix}.`
}

function staleLocalMainLine(dir) {
  // #117 — warn when the LOCAL default-branch ref has drifted from origin/<branch>. A stale local
  // `main` (git fetch updates origin/main but not the local ref) makes `git diff main` compare
  // against merged-away state. Inject-only, never throws; returns null to skip (no default branch,
  // either ref missing, refs equal, or any failure). Reuses the origin ref gate0Line already fetched.
  const defBranch = defaultBranch(dir)
  if (!defBranch) return null
  const local = run(['rev-parse', '--verify', '--quiet', defBranch], dir, 3000)
  const remote = run(['rev-parse', '--verify', '--quiet', `origin/${defBranch}`], dir, 3000)
  if (!local.ok || !remote.ok) return null
  const lsha = local.stdout.trim()
  const rsha = remote.stdout.trim()
  if (!lsha || !rsha || lsha === rsha) return null
  return (
    `⚠ GATE-0: your LOCAL '${defBranch}' ref (${lsha.slice(0, 7)}) differs from ` +
    `origin/${defBranch} (${rsha.slice(0, 7)}) — it's stale. Run \`git fetch\` and rebase it, and ` +
    `always diff against \`origin/${defBranch}\`, never bare local \`${defBranch}\`.`
  )
}

const dir = process.env.CLAUDE_PROJECT_DIR || process.cwd()
const lines = [`[${path.basename(dir)} session]`]
try {
  const branch = execFileSync('git', ['branch', '--show-current'], { cwd: dir, encoding: 'utf8' }).trim()
  const dirty = execFileSync('git', ['status', '--porcelain'], { cwd: dir, encoding: 'utf8' }).trim()
  lines.push(`Branch: ${branch}${dirty ? ' (dirty)' : ' (clean)'}`)
} catch {
  /* not a git repo / git missing — skip */
}

// H4 — GATE-0 behind-count injector. Fully isolated try/catch: a bug here must never crash the
// hook or block the session (SessionStart is inject-only, never blocking).
try {
  const gate0 = gate0Line(dir)
  if (gate0) lines.push(gate0)
} catch {
  /* fail open — never crash SessionStart */
}

// #117 — GATE-0 code-freshness: warn when the LOCAL default-branch ref is stale vs origin/<branch>.
// Isolated try/catch (inject-only, never blocks).
try {
  const stale = staleLocalMainLine(dir)
  if (stale) lines.push(stale)
} catch {
  /* fail open — never crash SessionStart */
}

console.log(lines.join('\n'))
