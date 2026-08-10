#!/usr/bin/env node
// PreToolUse hook (Node) — block destructive ops. Reads the hook payload (JSON) on stdin.
const { execFileSync } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const READONLY_PATHS = [] // customize per project, e.g. ['/vendor/', '/data/raw/']
const BLOCKED_WRITE = ['.env']
const DANGEROUS_DB = ['DROP TABLE', 'DROP DATABASE', 'TRUNCATE', 'ALTER TABLE', 'DROP INDEX']

// H1 — test-lock: deny bare test-runner invocations unless wrapped in `cc-worktrees test -- ...`
// or overridden via CCWT_ALLOW_UNLOCKED_TESTS=1. Anchored at the START of a shell segment (after
// stripping leading `VAR=val`/`env`/`npx`/path-prefix tokens) so we never match e.g. "npm run testify".
const CCWT_WRAPPED_RE = /cc-worktrees\s+test\b/
const SHELL_SEGMENT_SPLIT_RE = /&&|\|\||;|\n|\|/
// Leading tokens stripped (in a loop, so combos like "env FOO=bar npx ./node_modules/.bin/jest"
// resolve) before anchoring TEST_LOCK_RE — this is a nudge-grade guard, not a shell parser: it does
// NOT attempt to see through `bash -c '...'` or `$(subshell)` wrapping (accepted limitation, see
// tests/test_pretooluse_guards.sh "H1-LIMIT" cases).
const LEADING_ENV_ASSIGN_RE = /^[A-Za-z_][A-Za-z0-9_]*=\S*\s+/
const LEADING_ENV_KEYWORD_RE = /^env\s+/
const LEADING_NPX_RE = /^npx\s+/
const LEADING_PATH_PREFIX_RE = /^(?:\.\/(?:[\w.-]+\/)*|(?:[\w.-]+\/)*node_modules\/\.bin\/)/
const LEADING_STRIP_PATTERNS = [LEADING_ENV_ASSIGN_RE, LEADING_ENV_KEYWORD_RE, LEADING_NPX_RE, LEADING_PATH_PREFIX_RE]
const TEST_LOCK_RE = /^(npm\s+run\s+test\b|npm\s+test\b|pytest\b|go\s+test\b|cargo\s+test\b|vitest\b|jest\b)/

function stripLeadingTokens(segment) {
  // Iteratively strips leading env-assignment / `env` / `npx` / path-prefix tokens so
  // "env FOO=bar npx ./node_modules/.bin/jest" resolves down to "jest" before anchoring.
  let seg = segment
  let changed = true
  while (changed) {
    changed = false
    for (const pattern of LEADING_STRIP_PATTERNS) {
      const newSeg = seg.replace(pattern, '')
      if (newSeg !== seg) {
        seg = newSeg
        changed = true
      }
    }
  }
  return seg
}

function segmentHasLeadingOverride(segment, name) {
  // True if `name=1` is a genuine LEADING env-assignment token of THIS shell segment (not merely
  // a substring mentioned elsewhere, e.g. inside a commit message or an echo — HIGH fix — and not
  // leading a DIFFERENT segment of the same command — MED fix: under real shell semantics
  // `VAR=1 true && git commit` only exports VAR to `true`, not to the following segment, so an
  // override must be scoped to the exact segment doing the guarded work, never "any segment").
  let seg = segment.trim()
  for (;;) {
    const m = seg.match(/^([A-Za-z_][A-Za-z0-9_]*)=(\S*)\s*/)
    if (!m) return false
    let val = m[2]
    // nice-to-have: tolerate a quoted value (CCWT_ALLOW_SECRETS='1') — strip matching quotes.
    if (val.length >= 2 && (val[0] === '"' || val[0] === "'") && val[val.length - 1] === val[0]) {
      val = val.slice(1, -1)
    }
    if (m[1] === name && val === '1') return true
    seg = seg.slice(m[0].length)
  }
}

function processEnvOverride(name) {
  // The hook process's own env (in case Claude Code invokes it as a child that inherits it) —
  // this legitimately applies globally, unlike a command-embedded assignment.
  return process.env[name] === '1'
}

// H2 — conventional-commit: permissive `type(scope)!: subject` grammar for an inline `git commit -m`.
// Types are matched case-sensitively lowercase-only per the conventional-commits spec (so
// "Feat: x" is denied, not silently normalized).
const CONVENTIONAL_COMMIT_RE =
  /^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]*\))?!?:\s+\S.*$/
const GIT_COMMIT_RE = /\bgit\s+commit\b/
const COMMIT_M_FLAG_RE = /(?:^|\s)(?:-m|--message)(?:=|\s+)("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\S+)/
const COMMIT_F_FLAG_RE = /(?:^|\s)(?:-F|--file)(?:=|\s+)\S+/
// Merge-commit default messages are exempt — git generates these, not the agent, and they don't
// follow (nor should be forced into) conventional-commit grammar.
const MERGE_COMMIT_MSG_RE = /^Merge (branch|remote-tracking branch|pull request)\b/

// H3 — secret-scan: obvious secrets in a staged diff. Overridable via CCWT_ALLOW_SECRETS=1 (see
// `segmentHasLeadingOverride` / `processEnvOverride` — leading env-assignment token of the
// COMMIT's own segment, or real process env; never an unanchored substring, never leaking from a
// different segment).
const AWS_KEY_RE = /AKIA[0-9A-Z]{16}/
const PRIVATE_KEY_RE = /-----BEGIN [A-Z ]*PRIVATE KEY-----/
// TODO(secret-scan): GENERIC_SECRET_RE only catches a QUOTED `key = "value"` assignment; an
// unquoted `KEY=value` (e.g. a bare .env-style line) is currently missed. Left as-is this pass —
// broadening risks false positives on ordinary code (`token = getToken()`-shaped lines, etc.) and
// needs its own design pass, not a drive-by widen.
const GENERIC_SECRET_RE = /\b(token|secret|api[_-]?key)\b\s*[:=]\s*["']([A-Za-z0-9+/=_-]{16,})["']/i

// H5 — PR-review reminder: INJECT-ONLY (PreToolUse can block, but this guard never does — a
// nudge, not a gate). Never calls block(); only ever returns a string or null.
const PR_MERGE_RE = /\bgh\s+pr\s+merge\b/

// H6 — docs-staleness reminder: INJECT-ONLY, same rationale as H5. Paths under these prefixes
// don't count as "source" for this heuristic — infra/config/docs dirs, not the kind of change
// that would make docs stale. `tests/`/`test/` included: a test-only commit is pure noise here —
// it never blocks either way, but nudging "check the docs" on a change that touched no product
// code is a false positive the reminder shouldn't produce.
const DOCS_STALENESS_EXCLUDED_PREFIXES = ['docs/', 'crew/', '.claude/', '.github/', 'tests/', 'test/']

// H7 — danger-guard: force-push to main/master, `git reset --hard <remote>/<branch>`, and `rm -rf`
// on sensitive/parent paths (extends the existing READONLY_PATHS rm-rf check below). Nudge-grade —
// same heuristic-not-shell-parser limitation as H1. Override CCWT_ALLOW_DANGER=1 — SEGMENT-SCOPED
// via `segmentHasLeadingOverride` (the #1 rule from the H1/H3 override-bypass saga: never a bare
// substring, never leak across a different shell segment).
const SENSITIVE_RM_RF_TARGETS = [
  '/', '/*', '~', '~/', '$HOME', '..', '../', '/etc', '/etc/', '/usr', '/usr/',
  '/bin', '/bin/', '/var', '/var/', '/System', '/System/', '/Users', '/Users/',
  '/home', '/home/',
]
const GIT_PUSH_RE = /\bgit\s+push\b/
const RESET_HARD_REMOTE_RE = /\bgit\s+reset\s+--hard\s+(\S+)/
// issue #111 — more working-tree/branch destroyers that discard uncommitted or unpushed work with no
// reflog recovery: `git clean -f[d]`, `git branch -D`, `git checkout .` / `git restore .`. Each is a
// block-with-safe-alternative, same nudge-grade heuristic as the rest of H7. We do NOT block ordinary
// `git push`. `-C <path>` is tolerated between `git` and the subcommand so it's not a bypass.
const GIT_CLEAN_RE = /\bgit\s+(?:-C\s+\S+\s+)?clean\b/
const GIT_BRANCH_RE = /\bgit\s+(?:-C\s+\S+\s+)?branch\b/
const GIT_CHECKOUT_REST_RE = /\bgit\s+(?:-C\s+\S+\s+)?checkout\b(.*)$/
const GIT_RESTORE_REST_RE = /\bgit\s+(?:-C\s+\S+\s+)?restore\b(.*)$/

function hasShortFlag(segment, ch) {
  // True if a clustered short flag containing `ch` is present (e.g. `-f`, `-fd`, `-xf`).
  return new RegExp('(?:^|\\s)-[A-Za-z]*' + ch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '[A-Za-z]*(?:\\s|$)').test(
    segment,
  )
}

function hasDotPathspec(rest) {
  // True if a bare `.` / `./` pathspec token appears in the args after the subcommand — the
  // 'discard EVERYTHING in the working tree' form of checkout/restore.
  return rest.split(/\s+/).some((tok) => tok === '.' || tok === './')
}

function destructiveWorktreeOp(segment) {
  // [label, safe-alternative] for a #111 destroyer in THIS segment, or null. `git clean` only acts
  // with a force flag (and not in `-n`/--dry-run preview mode); `git branch -D` (or explicit
  // `--delete --force`) force-deletes; `git checkout .`/`git restore .` discard the whole worktree.
  if (GIT_CLEAN_RE.test(segment)) {
    const forced = hasShortFlag(segment, 'f') || segment.includes('--force')
    const preview = hasShortFlag(segment, 'n') || segment.includes('--dry-run')
    if (forced && !preview) {
      return [
        'git clean -f',
        'irrecoverably deletes untracked files — preview with `git clean -n` or save them with ' +
          '`git stash -u` first',
      ]
    }
  }
  if (GIT_BRANCH_RE.test(segment)) {
    if (hasShortFlag(segment, 'D') || (segment.includes('--delete') && segment.includes('--force'))) {
      return [
        'git branch -D',
        'force-deletes a branch even if unmerged — use `git branch -d` (refuses to drop unmerged ' +
          "work) or confirm it's merged/pushed first",
      ]
    }
  }
  let m = GIT_CHECKOUT_REST_RE.exec(segment)
  if (m && hasDotPathspec(m[1])) {
    return [
      'git checkout .',
      'discards ALL uncommitted working-tree changes — stash them (`git stash`) or restore ' +
        'specific files by name instead',
    ]
  }
  m = GIT_RESTORE_REST_RE.exec(segment)
  if (m && hasDotPathspec(m[1])) {
    const rest = m[1]
    const staged = rest.includes('--staged') || hasShortFlag(rest, 'S')
    const worktree = rest.includes('--worktree') || hasShortFlag(rest, 'W')
    // S1 fix (#111): `git restore` defaults to the WORKING TREE unless --staged/-S is given.
    // `git restore --staged .` only unstages (index-only, working tree untouched) — the standard
    // "unstage everything", NOT destructive. Destructive only when the working tree is actually
    // touched: an explicit --worktree/-W, or the default (no --staged).
    if (worktree || !staged) {
      return [
        'git restore .',
        'discards ALL uncommitted working-tree changes — stash them (`git stash`) or restore ' +
          'specific files by name instead',
      ]
    }
  }
  return null
}
// MED fix: `@{upstream}`/`@{u}` are remote-tracking shorthand too, not just an explicit `origin/x`.
const RESET_HARD_UPSTREAM_SHORTHAND = ['@{upstream}', '@{u}']

// H8 — protected-branch: `git commit` blocks unconditionally when the CURRENT branch (via `git
// rev-parse --abbrev-ref HEAD` in the payload's cwd, or a `-C <path>` repo if given) is
// main/master — a commit always lands on the current branch. `git push` is TARGET-aware (2nd
// fix-up, HIGH-1 still open after the 1st pass): it blocks ONLY when the push's actual
// DESTINATION resolves to main/master, not merely because you happen to be sitting on main —
// `git push origin feature-x` while on main must ALLOW. Fail-open if not a repo / detached HEAD /
// the subprocess errors. Override CCWT_ALLOW_PROTECTED=1 (segment-scoped).
const PROTECTED_BRANCHES = ['main', 'master']
// `git -C <path> ...` targets a DIFFERENT repo than the payload's own cwd — honor it when present
// so `git -C other-repo commit` is checked against other-repo's branch, not cwd's.
const GIT_DASH_C_RE = /\bgit\s+-C\s+(\S+)/
// The plain GIT_COMMIT_RE/GIT_PUSH_RE (`\bgit\s+commit\b` / `\bgit\s+push\b`) don't match when a
// `-C <path>` sits between "git" and the subcommand — H8 needs its OWN trigger checks that
// tolerate it, else the -C fix above is never actually reached.
const GIT_COMMIT_OR_PUSH_WITH_DASH_C_RE = /\bgit\s+(?:-C\s+\S+\s+)?(?:commit|push)\b/
const GIT_PUSH_WITH_DASH_C_RE = /\bgit\s+(?:-C\s+\S+\s+)?push\b(.*)$/

// H9 — giant-file: block staging a file over CCWT_MAX_FILE_MB (default 10) via `git add`/`git
// commit`. Override CCWT_ALLOW_BIGFILE=1 (segment-scoped). HIGH fix: the hook fires PRE-execution
// — at hook-check time NOTHING has actually been staged yet, so `git add -A`/`.`/`-u` (no
// explicit path on the command line) must be resolved to what `git status` says WOULD be staged,
// not just the literal path arguments — closes the `git add -A && git commit` bypass.
const GIT_ADD_RE = /\bgit\s+add\b/
const ADD_STAGES_EVERYTHING_FLAGS = ['-A', '--all', '-u', '--update']
const DEFAULT_MAX_FILE_MB = 10

// H10 — secret-file staging: block staging an obviously-secret FILE by NAME (complements H3,
// which scans staged diff CONTENT — H10 catches the file itself). MED fix: `.env*` is now an
// ALLOW-LIST (deny everything starting with `.env`, case-insensitively, EXCEPT these known-safe
// suffixes) — was an allow-by-default denylist that missed `.env.local`/`.env.production`/`.ENV`.
// Override CCWT_ALLOW_SECRET_FILE=1 (segment-scoped).
const SECRET_FILENAME_ALLOW = ['.env.example', '.env.sample', '.env.test']

function resolveGitCwd(segment, cwd) {
  // MED fix (H8): `git -C <path> ...` targets a DIFFERENT repo than the payload's own cwd —
  // resolve it (relative to cwd if not absolute) and use THAT for the branch check, instead of
  // checking cwd's own repo (or failing open because cwd itself isn't a repo at all).
  const m = GIT_DASH_C_RE.exec(segment)
  if (!m) return cwd
  const target = m[1].replace(/^['"]|['"]$/g, '')
  return path.isAbsolute(target) ? target : path.join(cwd || '.', target)
}

function currentBranch(cwd) {
  // Best-effort current branch name; null on ANY failure (not a repo, detached HEAD, git missing,
  // timeout) — shared by H7 (implicit force-push target) and H8 (protected-branch check); both
  // callers fail OPEN when this returns null.
  let out
  try {
    out = execFileSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'], {
      cwd: cwd || undefined,
      encoding: 'utf8',
      timeout: 3000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
  } catch {
    return null
  }
  const branch = out.trim()
  if (!branch || branch === 'HEAD') return null // detached HEAD prints the literal string "HEAD"
  return branch
}

function stagedNames(cwd) {
  // `git diff --cached --name-only`, fail-open ([]) on any error. Shared by H6 (docs-staleness),
  // H9 (giant-file at commit time), and H10 (secret-file at commit time).
  let out
  try {
    out = execFileSync('git', ['diff', '--cached', '--name-only'], {
      cwd: cwd || undefined,
      encoding: 'utf8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
  } catch {
    return []
  }
  return out.split('\n').map((p) => p.trim()).filter(Boolean)
}

function isRmRf(segment) {
  // Best-effort rm -rf / -fr / --recursive+--force detector — a nudge-grade guard, not a shell
  // parser; doesn't try to see through `bash -c` or aliases (same class of limitation as H1).
  if (!/\brm\b/.test(segment)) return false
  const hasR = /(?:^|\s)-[a-zA-Z]*r[a-zA-Z]*(?:\s|$)/.test(segment) || segment.includes('--recursive')
  const hasF = /(?:^|\s)-[a-zA-Z]*f[a-zA-Z]*(?:\s|$)/.test(segment) || segment.includes('--force')
  return hasR && hasF
}

function rmRfSensitiveTarget(segment) {
  if (!isRmRf(segment)) return null
  for (const target of SENSITIVE_RM_RF_TARGETS) {
    const re = new RegExp('(?:^|\\s)' + target.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?:\\s|$)')
    if (re.test(segment)) return target
  }
  return null
}

function pushCandidates(segment, cwd) {
  // ALL candidate destination branches a `git push` in THIS segment could update, each paired
  // with whether THAT specific ref is force-pushed — [{branch, forced}, ...]. SHARED by H7 (only
  // cares about FORCED candidates) and H8 (2nd fix-up: cares about ALL candidates, forced or not
  // — direct-to-protected-branch is the concern regardless of force). 3rd fix-up (narrow refspec
  // bypasses the auditor's deeper probe found):
  //   1. A single push can update MULTIPLE refs at once (`git push origin main feature`) — only
  //      checking the LAST non-flag token missed an EARLIER protected one (`git push origin main
  //      feature` let `main` through). Every non-flag token AFTER the remote is now evaluated as
  //      its own candidate.
  //   2. git's short per-ref force marker — a leading `+` directly on a ref, e.g. `+main` — is
  //      EXACTLY as dangerous as `--force ... main` but carries no `--force`/`-f` flag anywhere
  //      in the command at all, so "is there a force flag present" alone missed it (the LONG form
  //      `+refs/heads/main` was accidentally caught because splitting on `/` and taking the last
  //      segment happened to still land on `main`; the SHORT form `+main` was not — `+` was never
  //      stripped before the comparison). Each token's leading `+` is now stripped before
  //      deriving the branch name, and that per-ref `+` ALSO counts as forced for THAT ref even
  //      with no `--force`/`-f` flag anywhere else in the command.
  // `HEAD` resolves to the CURRENT branch; a `src:dst` refspec is evaluated on its `dst` side.
  // Returns [] if this isn't a `git push` at all, or if it's a tags/all-branches push with no
  // single identifiable branch destination (`--tags`/`-t`/`--all` and no other ref arg).
  const m = GIT_PUSH_WITH_DASH_C_RE.exec(segment)
  if (!m) return []
  const rest = m[1]
  const tokens = rest.split(/\s+/).filter(Boolean)
  const nonFlagTokens = tokens.filter((t) => !t.startsWith('-'))
  if (!nonFlagTokens.length && tokens.some((t) => t === '--tags' || t === '-t' || t === '--all')) {
    return [] // pushes tags / all branches — no single branch destination to protect
  }
  const globalForce = /--force(?:-with-lease)?\b|(?:^|\s)-[a-zA-Z]*f[a-zA-Z]*(?:\s|$)/.test(rest)
  if (nonFlagTokens.length >= 2) {
    // nonFlagTokens[0] is the remote; EVERY token after it is a candidate ref destination — a
    // push can update more than one ref at once, and each must be checked independently.
    const candidates = []
    for (const tok of nonFlagTokens.slice(1)) {
      const forced = globalForce || tok.startsWith('+')
      const ref = tok.startsWith('+') ? tok.slice(1) : tok // strip the short force-refspec marker
      const parts = ref.split(':')
      const name = parts[parts.length - 1].split('/').pop()
      const branch = name === 'HEAD' ? currentBranch(cwd) : name
      candidates.push({ branch, forced })
    }
    return candidates
  }
  // 0 or 1 non-flag tokens (no explicit branch/refspec — just maybe a bare remote name) — this
  // push targets the CURRENT branch by default (real git push.default semantics).
  return [{ branch: currentBranch(cwd), forced: globalForce }]
}

function resetHardRemoteTarget(segment) {
  const m = RESET_HARD_REMOTE_RE.exec(segment)
  if (!m) return null
  const target = m[1]
  if (RESET_HARD_UPSTREAM_SHORTHAND.includes(target)) return target // MED fix: @{upstream} / @{u}
  return /^[\w.-]+\/[\w.-]+$/.test(target) ? target : null
}

function extractAddPaths(segment) {
  // Non-flag argument tokens after `git add` — a small quote-aware tokenizer (handles a single-
  // or double-quoted path with spaces) so it round-trips like the Python shlex-based version.
  const m = segment.match(/\bgit\s+add\b(.*)$/)
  if (!m) return []
  const rest = m[1]
  const tokens = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let tm
  while ((tm = re.exec(rest)) !== null) {
    tokens.push(tm[1] !== undefined ? tm[1] : tm[2] !== undefined ? tm[2] : tm[3])
  }
  return tokens.filter((t) => t && !t.startsWith('-'))
}

function addSegmentStagesEverything(segment) {
  // True for `git add -A`/`--all`/`-u`/`--update`, or a bare `.`/`./` path — any form that stages
  // more than the literal path arguments on the command line.
  const m = segment.match(/\bgit\s+add\b(.*)$/)
  if (!m) return false
  const rest = m[1]
  const tokens = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let tm
  while ((tm = re.exec(rest)) !== null) {
    tokens.push(tm[1] !== undefined ? tm[1] : tm[2] !== undefined ? tm[2] : tm[3])
  }
  if (tokens.some((t) => ADD_STAGES_EVERYTHING_FLAGS.includes(t))) return true
  const nonFlag = tokens.filter((t) => t && !t.startsWith('-'))
  return nonFlag.some((p) => p === '.' || p === './')
}

function wouldBeStagedByAddAll(cwd) {
  // Enumerates what `git status --porcelain` reports as changed (tracked-modified + all
  // untracked, following .gitignore) — the set of paths a `git add -A`/`.`/`-u` WOULD stage.
  // Fail-open ([]) on any error. HIGH fix: the hook fires PRE-execution, so at hook-check time
  // nothing has actually been staged by a `git add -A` in the SAME command yet — checking only
  // literal path arguments (empty for -A/-u, a bare directory for `.`) missed this entirely,
  // letting `git add -A && git commit ...` evade both H9 (giant-file) and H10 (secret-file).
  let out
  try {
    out = execFileSync('git', ['status', '--porcelain', '--untracked-files=all'], {
      cwd: cwd || undefined,
      encoding: 'utf8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
  } catch {
    return []
  }
  const paths = []
  for (const line of out.split('\n')) {
    if (line.length < 4) continue
    let rest = line.slice(3).trim()
    if (rest.includes(' -> ')) rest = rest.split(' -> ')[1].trim() // rename: keep the NEW path
    if (rest.length >= 2 && rest[0] === '"' && rest[rest.length - 1] === '"') {
      rest = rest.slice(1, -1)
    }
    if (rest) paths.push(rest)
  }
  return paths
}

function addCommandTargets(segment, cwd) {
  // Files a `git add` in THIS segment would actually stage — either the explicit path arguments,
  // or (for -A/--all/-u/--update/a bare '.') everything `git status` reports as changed. The
  // single call site H9 and H10 both use instead of `extractAddPaths` directly.
  if (addSegmentStagesEverything(segment)) return wouldBeStagedByAddAll(cwd)
  return extractAddPaths(segment)
}

function stagedBlobSizeMb(cwd, path) {
  // Size (MB) of PATH as staged in the git index (`git cat-file -s :path`) — robust regardless of
  // working-tree state (the file may have changed or been deleted since it was staged). null on
  // any failure (fail open).
  let out
  try {
    out = execFileSync('git', ['cat-file', '-s', `:${path}`], {
      cwd: cwd || undefined,
      encoding: 'utf8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
  } catch {
    return null
  }
  const n = parseInt(out.trim(), 10)
  return Number.isNaN(n) ? null : n / (1024 * 1024)
}

function maxFileMb() {
  const v = parseFloat(process.env.CCWT_MAX_FILE_MB)
  return Number.isFinite(v) ? v : DEFAULT_MAX_FILE_MB
}

function isSecretFilename(filePath) {
  // Case-insensitive throughout (MED fix — `.ENV` must deny same as `.env`).
  const baseLower = filePath.split('/').pop().toLowerCase()
  if (baseLower.startsWith('.env')) {
    // MED fix: ALLOW-LIST, not a denylist — every `.env*` is secret EXCEPT these known-safe
    // suffixes, so `.env.local`/`.env.production`/etc. (anything not explicitly allow-listed)
    // denies. The old version only denied the bare `.env` name, missing every real-world
    // per-environment variant.
    return !SECRET_FILENAME_ALLOW.includes(baseLower)
  }
  if (baseLower.endsWith('.pem')) return true
  if (baseLower === 'id_rsa') return true
  if (baseLower.endsWith('.key')) return true
  if (baseLower === 'credentials.json') return true
  if (baseLower.includes('service-account') && baseLower.endsWith('.json')) return true
  return false
}

function checkTestLock(cmd, block) {
  if (!cmd.trim()) return
  if (processEnvOverride('CCWT_ALLOW_UNLOCKED_TESTS')) return
  if (CCWT_WRAPPED_RE.test(cmd)) return
  for (const segment of cmd.split(SHELL_SEGMENT_SPLIT_RE)) {
    const seg = stripLeadingTokens(segment.trim()).trim()
    if (TEST_LOCK_RE.test(seg)) {
      // MED fix: the override must lead THIS segment (the one that matched), not merely "any
      // segment of the whole command" — else "VAR=1 true && npm test" would wrongly inherit an
      // override that real shell semantics never actually gives to "npm test".
      if (segmentHasLeadingOverride(segment, 'CCWT_ALLOW_UNLOCKED_TESTS')) continue
      block(
        'Blocked: bare test-runner invocation. Re-run via `cc-worktrees test -- <cmd>` to hold ' +
          'the per-repo test lock, or set CCWT_ALLOW_UNLOCKED_TESTS=1 to override.',
      )
      return
    }
  }
}

function checkConventionalCommit(cmd, block) {
  if (!GIT_COMMIT_RE.test(cmd)) return
  if (COMMIT_F_FLAG_RE.test(cmd)) return // -F/--file path — not our concern here
  const m = cmd.match(COMMIT_M_FLAG_RE)
  if (!m) return // no inline -m → interactive/editor commit, don't block
  let msg = m[1]
  if (msg.length >= 2 && (msg[0] === '"' || msg[0] === "'") && msg[msg.length - 1] === msg[0]) {
    msg = msg.slice(1, -1)
  }
  if (MERGE_COMMIT_MSG_RE.test(msg.trim())) return // merge-commit default message — exempt
  if (!CONVENTIONAL_COMMIT_RE.test(msg.trim())) {
    block(
      `Blocked: commit message '${msg}' doesn't match conventional-commit grammar ` +
        '`type(scope)!: subject` (types: feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert).',
    )
  }
}

function checkSecretScan(cmd, cwd, block) {
  // KNOWN LIMITATION (Increment-4 audit, documented not silently left inconsistent): unlike H6/
  // H9/H10, this does NOT see a brand-new secret introduced by a SAME-COMMAND chained
  // `git add -A && git commit ...` — this reads `git diff --cached` at hook-check time, which is
  // PRE-execution (nothing in the chain has actually run yet), so a file `git add -A` would newly
  // stage isn't reflected here. H6/H9/H10 closed the equivalent gap cheaply because they only
  // need FILENAMES (`git status` enumeration); closing it here would mean reading and
  // regex-scanning the CONTENT of every about-to-be-staged file (raw untracked-file bytes +
  // working-tree diffs for modified-tracked files) — a real cost/complexity increase (binary
  // files, huge files, encoding) that's its own design pass, not a drive-by fix — same class of
  // call as the existing GENERIC_SECRET_RE TODO above. Pinned by
  // tests/test_pretooluse_guards.sh's "H3-LIMIT" case so this gap can't silently regress further
  // or be mistaken for "already handled".
  //
  // Find the segment that actually does the `git commit` (MED fix: the override must be scoped
  // to THIS segment, not "any segment of the whole command" — see checkTestLock for the same
  // reasoning). If more than one segment matches, the first is used — multiple chained commits in
  // one Bash call is an edge case outside this guard's stated scope.
  const commitSegment = cmd.split(SHELL_SEGMENT_SPLIT_RE).find((seg) => GIT_COMMIT_RE.test(seg))
  if (commitSegment === undefined) return
  if (processEnvOverride('CCWT_ALLOW_SECRETS')) return
  if (segmentHasLeadingOverride(commitSegment, 'CCWT_ALLOW_SECRETS')) return
  let diff
  try {
    diff = execFileSync('git', ['diff', '--cached'], {
      cwd: cwd || undefined,
      encoding: 'utf8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
  } catch {
    return // fail open (no git, not a repo, non-zero exit, etc.)
  }
  if (AWS_KEY_RE.test(diff) || PRIVATE_KEY_RE.test(diff) || GENERIC_SECRET_RE.test(diff)) {
    block(
      'Blocked: staged diff appears to contain a secret (AWS key / private-key header / ' +
        'token-like assignment). Review `git diff --cached`, remove it, or set ' +
        'CCWT_ALLOW_SECRETS=1 to override.',
    )
  }
}

function checkPrReviewReminder(cmd) {
  // H5 — never blocks. A `gh pr merge` anywhere in the command gets a /review nudge.
  if (PR_MERGE_RE.test(cmd)) {
    return 'Reminder: run /review on this PR before merging (rules/workflow.md REVIEW phase).'
  }
  return null
}

function checkDocsStalenessReminder(cmd, cwd) {
  // H6 — never blocks. If a `git commit`'s staged diff touches source but NOT docs/, nudge a
  // docs-impact-agent check. Uses `stagedNames` (shared with H9/H10) — same event/trigger as H3's
  // secret scan, but a separate call since H3 needs the diff CONTENT, this needs file PATHS.
  //
  // Broader-fix (Increment-4 audit): unlike H3 (which needs file CONTENT and is documented as a
  // known gap for this same scenario — see `checkSecretScan`), this is CHEAP to close with the
  // same H9/H10 enumeration since it only needs filenames — merge in what a same-command chained
  // `git add -A`/`.`/`-u` WOULD stage so the reminder isn't silently skipped.
  if (!GIT_COMMIT_RE.test(cmd)) return null
  const paths = stagedNames(cwd)
  for (const segment of cmd.split(SHELL_SEGMENT_SPLIT_RE)) {
    if (addSegmentStagesEverything(segment)) {
      paths.push(...wouldBeStagedByAddAll(cwd))
      break
    }
  }
  if (!paths.length) return null // nothing staged — nothing to flag
  const touchesDocs = paths.some((p) => p.startsWith('docs/'))
  const touchesSource = paths.some((p) => !DOCS_STALENESS_EXCLUDED_PREFIXES.some((pre) => p.startsWith(pre)))
  if (touchesSource && !touchesDocs) {
    return (
      'Reminder: this commit touches source but not docs/ — consider running docs-impact-agent ' +
      'to check for stale docs.'
    )
  }
  return null
}

function checkDangerGuard(cmd, cwd, block) {
  // KNOWN LIMITATION, deliberately NOT solved (Increment-4 audit, LOW-MED): `cd / && rm -rf *`
  // evades `rmRfSensitiveTarget` — we don't track cwd across `&&`-joined segments, and a bare
  // glob (`*`) isn't in SENSITIVE_RM_RF_TARGETS at all. Solving the first half needs a real
  // cwd-tracking state machine across segments (out of scope for a nudge-grade guard); solving
  // the second half by treating a bare `*` as sensitive would false-positive on completely
  // ordinary cleanup like `rm -rf build/*` or `rm -rf dist/*`. Pinned by
  // tests/test_pretooluse_guards.sh's "H7-LIMIT" case (asserts this is NOT detected) so the gap
  // stays a documented, intentional choice rather than a silent regression waiting to be found.
  if (processEnvOverride('CCWT_ALLOW_DANGER')) return
  for (const segment of cmd.split(SHELL_SEGMENT_SPLIT_RE)) {
    let reason = null
    const rmTarget = rmRfSensitiveTarget(segment)
    if (rmTarget !== null) {
      reason =
        `Blocked: 'rm -rf' targeting a sensitive/parent path ('${rmTarget}') looks catastrophic, ` +
        'not a normal cleanup.'
    } else {
      const forcedProtected = pushCandidates(segment, cwd).find(
        (c) => c.forced && PROTECTED_BRANCHES.includes(c.branch),
      )
      if (forcedProtected) {
        reason =
          `Blocked: force-push to protected branch '${forcedProtected.branch}'. Force-pushing to ` +
          'main/master rewrites shared history.'
      } else {
        const resetTarget = resetHardRemoteTarget(segment)
        if (resetTarget !== null) {
          reason =
            `Blocked: 'git reset --hard ${resetTarget}' discards local commits relative to a ` +
            'remote-tracking ref — likely destroys unpushed work.'
        } else {
          const dop = destructiveWorktreeOp(segment) // issue #111
          if (dop !== null) {
            reason = `Blocked: '${dop[0]}' ${dop[1]}.`
          }
        }
      }
    }
    if (reason === null) continue
    if (segmentHasLeadingOverride(segment, 'CCWT_ALLOW_DANGER')) continue
    block(reason + ' Set CCWT_ALLOW_DANGER=1 to override.')
  }
}

function checkProtectedBranch(cmd, cwd, block) {
  if (processEnvOverride('CCWT_ALLOW_PROTECTED')) return
  for (const segment of cmd.split(SHELL_SEGMENT_SPLIT_RE)) {
    if (!GIT_COMMIT_OR_PUSH_WITH_DASH_C_RE.test(segment)) continue
    if (segmentHasLeadingOverride(segment, 'CCWT_ALLOW_PROTECTED')) continue
    const effectiveCwd = resolveGitCwd(segment, cwd)
    let branch, action
    if (GIT_PUSH_WITH_DASH_C_RE.test(segment)) {
      // 2nd fix-up (HIGH-1 still open after the 1st pass): TARGET-aware, not "current branch is
      // protected" unconditionally — `git push origin feature-x` while on main must ALLOW; only
      // the push's actual DESTINATION(S) matter here (3rd fix-up: a push can update MULTIPLE
      // refs at once — `git push origin main feature` — so ANY candidate resolving to a
      // protected branch blocks the whole push, not just the last one).
      const hit = pushCandidates(segment, effectiveCwd).find((c) => PROTECTED_BRANCHES.includes(c.branch))
      branch = hit ? hit.branch : undefined
      action = 'push'
    } else {
      // `git commit` — a commit always lands on the CURRENT branch, so this stays unconditional
      // (unchanged from the 1st pass).
      branch = currentBranch(effectiveCwd)
      action = 'commit'
    }
    if (PROTECTED_BRANCHES.includes(branch)) {
      block(
        `Blocked: direct git ${action} on protected branch '${branch}'. Use a feature branch + ` +
          'PR, or set CCWT_ALLOW_PROTECTED=1 to override.',
      )
    }
  }
}

function checkGiantFile(cmd, cwd, block) {
  if (processEnvOverride('CCWT_ALLOW_BIGFILE')) return
  const maxMb = maxFileMb()
  for (const segment of cmd.split(SHELL_SEGMENT_SPLIT_RE)) {
    if (GIT_ADD_RE.test(segment)) {
      // Pre-staging: the file isn't in the index yet at hook-check-time, so check its size on
      // disk — from the command's own path arguments, OR (HIGH fix) from `git status` if this is
      // a stages-everything form (-A/-u/`.`) that names no explicit paths.
      for (const p of addCommandTargets(segment, cwd)) {
        const full = path.isAbsolute(p) ? p : path.join(cwd || '.', p)
        let sizeMb
        try {
          const st = fs.statSync(full)
          if (!st.isFile()) continue // a directory / doesn't exist — nudge-grade, not a shell parser
          sizeMb = st.size / (1024 * 1024)
        } catch {
          continue
        }
        if (sizeMb > maxMb) {
          if (segmentHasLeadingOverride(segment, 'CCWT_ALLOW_BIGFILE')) continue
          block(
            `Blocked: '${p}' is ${sizeMb.toFixed(1)}MB, over the ${maxMb}MB limit ` +
              '(CCWT_MAX_FILE_MB). Set CCWT_ALLOW_BIGFILE=1 to override.',
          )
        }
      }
    } else if (GIT_COMMIT_RE.test(segment)) {
      // Post-staging: the file(s) were staged by an EARLIER `git add` call, so check the index's
      // own blob size (robust even if the working-tree file since changed/gone).
      for (const p of stagedNames(cwd)) {
        const sizeMb = stagedBlobSizeMb(cwd, p)
        if (sizeMb !== null && sizeMb > maxMb) {
          if (segmentHasLeadingOverride(segment, 'CCWT_ALLOW_BIGFILE')) continue
          block(
            `Blocked: staged file '${p}' is ${sizeMb.toFixed(1)}MB, over the ${maxMb}MB limit ` +
              '(CCWT_MAX_FILE_MB). Set CCWT_ALLOW_BIGFILE=1 to override.',
          )
        }
      }
    }
  }
}

function checkSecretFileStaging(cmd, cwd, block) {
  if (processEnvOverride('CCWT_ALLOW_SECRET_FILE')) return
  for (const segment of cmd.split(SHELL_SEGMENT_SPLIT_RE)) {
    if (GIT_ADD_RE.test(segment)) {
      for (const p of addCommandTargets(segment, cwd)) {
        if (!isSecretFilename(p)) continue
        if (segmentHasLeadingOverride(segment, 'CCWT_ALLOW_SECRET_FILE')) continue
        block(
          `Blocked: '${p}' looks like a secret file (.env/*.pem/id_rsa/*.key/credentials.json/` +
            "*service-account*.json) — don't stage it. Set CCWT_ALLOW_SECRET_FILE=1 to override.",
        )
      }
    } else if (GIT_COMMIT_RE.test(segment)) {
      for (const p of stagedNames(cwd)) {
        if (!isSecretFilename(p)) continue
        if (segmentHasLeadingOverride(segment, 'CCWT_ALLOW_SECRET_FILE')) continue
        block(
          `Blocked: staged file '${p}' looks like a secret file (.env/*.pem/id_rsa/*.key/` +
            'credentials.json/*service-account*.json). Set CCWT_ALLOW_SECRET_FILE=1 to override.',
        )
      }
    }
  }
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
  const name = data.tool_name || ''
  const input = data.tool_input || {}
  const block = (reason) => {
    console.log(JSON.stringify({ decision: 'block', reason }))
    process.exit(2)
  }

  if (name === 'Bash') {
    const cmd = input.command || ''
    for (const p of READONLY_PATHS) {
      if (cmd.includes('rm -rf') && cmd.includes(p)) block(`Blocked: rm -rf inside read-only ${p}`)
    }
    for (const pat of BLOCKED_WRITE) {
      if ([`> ${pat}`, `>> ${pat}`].some((s) => cmd.includes(s))) {
        block(`Blocked: do not overwrite ${pat} via shell`)
      }
    }
    // Word-boundary match after scrubbing quoted strings inside a `git commit …` segment ONLY
    // (a commit message cannot execute; scrub stops at ;|&| so a chained real op still trips).
    // Deliberately NO heredoc stripping — heredocs are an execution path (`psql <<SQL`); stripping
    // them was live-proven to let a real DROP through (ADR 0008). Mirrors pre_tool_use.py exactly.
    const dbScrubbed = cmd.replace(/\bgit\s+commit\b[^\n;&|]*/g, (seg) => seg.replace(/(['"]).*?\1/g, ' '))
    for (const op of DANGEROUS_DB) {
      if (cmd.includes('--dry-run')) break
      const opRe = new RegExp('\\b' + op.replace(/ /g, '\\s+') + '\\b', 'i')
      if (opRe.test(dbScrubbed)) {
        block(`Blocked: destructive DB op '${op}' — use --dry-run first`)
      }
    }

    // H1/H2/H3 — each wrapped so a bug in one guard fails OPEN, never crashes the hook.
    try {
      checkTestLock(cmd, block)
    } catch {
      /* fail open */
    }
    try {
      checkConventionalCommit(cmd, block)
    } catch {
      /* fail open */
    }
    try {
      checkSecretScan(cmd, data.cwd || '', block)
    } catch {
      /* fail open */
    }

    // H7/H8/H9/H10 — each wrapped so a bug in one guard fails OPEN, never crashes the hook.
    try {
      checkDangerGuard(cmd, data.cwd || '', block)
    } catch {
      /* fail open */
    }
    try {
      checkProtectedBranch(cmd, data.cwd || '', block)
    } catch {
      /* fail open */
    }
    try {
      checkGiantFile(cmd, data.cwd || '', block)
    } catch {
      /* fail open */
    }
    try {
      checkSecretFileStaging(cmd, data.cwd || '', block)
    } catch {
      /* fail open */
    }

    // H5/H6 — INJECT-ONLY reminders. Run AFTER every block-capable check above (any of which may
    // already have exited via block()/process.exit(2)); collected into ONE additionalContext
    // payload rather than one JSON blob per reminder.
    const reminders = []
    try {
      const r = checkPrReviewReminder(cmd)
      if (r) reminders.push(r)
    } catch {
      /* fail open */
    }
    try {
      const r = checkDocsStalenessReminder(cmd, data.cwd || '')
      if (r) reminders.push(r)
    } catch {
      /* fail open */
    }
    if (reminders.length) {
      console.log(
        JSON.stringify({
          hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: reminders.join('\n') },
        }),
      )
    }
  } else if (name === 'Write' || name === 'Edit') {
    const fp = input.file_path || ''
    for (const p of READONLY_PATHS) {
      if (p && fp.includes(p)) block(`Blocked: ${p} is read-only`)
    }
  }
  process.exit(0)
})
