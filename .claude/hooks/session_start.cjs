#!/usr/bin/env node
// SessionStart hook (Node) — print git status + GATE-0 behind-count (H4) into the session context.
// SessionStart is INJECT-ONLY (researcher §4) — it can never block, so every path here exits 0 and
// never throws uncaught. Best-effort `git fetch` (short timeout, fails SILENTLY offline), then
// compute the local branch's behind-count vs the default remote branch. Gracefully skips (no
// crash) when: not a git repo, detached HEAD / no branch, no `origin` remote, or fetch/rev-list
// itself fails.
const { execFileSync } = require('node:child_process')
const path = require('node:path')

// context-reinjection — single-sourced concise reminder text (must stay byte-identical to the
// CONCISE_REMINDER constant in hooks/session_start.py.tmpl). Pointer-based, not a data dump (G2):
// the specifics live in the files it points to, which are always current. Bounded to ~15 lines (G1).
const CONCISE_REMINDER = `⚠ Context was just compacted/resumed — your memory of this session may be stale. Trust the
durable records, not recall.

The two laws: Design → Code → Prove.
  GATE-1 — design before code (no implementation without an approved design).
  GATE-2 — evidence before "done" (fresh output THIS turn, never "should pass").

Re-read before acting: HANDOFF.md, crew/*.md (if you're in a crew), and the active task's
docs/superpowers/specs/ + docs/superpowers/plans/ files.

Verify against the durable records + origin/main before acting — don't assume.`

function readSource() {
  // Best-effort read of the SessionStart hook's `source` field from stdin JSON. Returns the
  // source string, or null if stdin is empty/unreadable/malformed (never throws) — the caller
  // treats null as the safe fallback (the FULL [Session Context] dump, not the concise reminder —
  // G3/GP1, flipped post-review per crew/auditor-context-reinjection.md Finding 1).
  try {
    const raw = require('node:fs').readFileSync(0, 'utf8')
    if (!raw || !raw.trim()) return null
    const data = JSON.parse(raw)
    return typeof data.source === 'string' ? data.source : null
  } catch {
    return null
  }
}

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

function reminderLine(dir) {
  // #7 — optional day-of-week reminder from `.claude/reminders.json` (PROJECT dir, opt-in). Maps a
  // 3-letter weekday short-name (e.g. "Mon") to a message; if today's key is present, returns that
  // message as a single line. Fail-open: absent, unreadable, or malformed reminders.json (not a
  // JSON object, wrong value type, etc.) returns null — never throws, never changes SessionStart's
  // exit code. `.claude/reminders.example.json` is a separate, INERT file — never read here.
  try {
    const fs = require('node:fs')
    const file = path.join(dir, '.claude', 'reminders.json')
    if (!fs.existsSync(file)) return null
    const data = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (typeof data !== 'object' || data === null || Array.isArray(data)) return null
    const today = new Date().toLocaleDateString('en-US', { weekday: 'short' })
    const message = data[today]
    return typeof message === 'string' && message ? message : null
  } catch {
    return null
  }
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

// context-reinjection — source-aware branch. ONLY an explicit source of "compact"/"resume" takes
// the concise-reminder path. Every other case — startup, clear, fork, any other explicit value,
// AND an unreadable/absent source (empty/malformed stdin, missing field) — falls back to the full
// [Session Context] dump (G3/GP1, flipped post-review per crew/auditor-context-reinjection.md
// Finding 1): silently dropping the H4 GATE-0 behind-count warning, the #117 stale-local-main
// warning, and HANDOFF surfacing on an unrecognized/unreadable source is a worse failure mode than
// being verbose on an actual compact/resume that somehow lost its source label — being "too safe"
// beats being silently blind to a stale branch.
const source = readSource()
const concise = source === 'compact' || source === 'resume'

if (concise) {
  const cLines = [CONCISE_REMINDER]
  try {
    const branch = execFileSync('git', ['branch', '--show-current'], { cwd: dir, encoding: 'utf8' }).trim()
    if (branch) cLines.push(`\nCurrent branch: ${branch}`)
  } catch {
    /* not a git repo / git missing — skip */
  }
  try {
    const reminder = reminderLine(dir)
    if (reminder) cLines.push(reminder)
  } catch {
    /* fail open — never crash SessionStart */
  }
  console.log(cLines.join('\n'))
} else {
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

  // #7 — day-of-week reminder, opt-in via .claude/reminders.json. Isolated try/catch (inject-only,
  // never blocks): a bug here must never crash SessionStart.
  try {
    const reminder = reminderLine(dir)
    if (reminder) lines.push(reminder)
  } catch {
    /* fail open — never crash SessionStart */
  }

  console.log(lines.join('\n'))
}
