import { expect, test } from 'claude-code/testing'
import { matchReason } from '../hooks/match.js'

// Real guard-message samples (anchors pinned from plugins/ct-hooks-py/hooks/guards/*.py and live refusals).
const WORKTREE = 'This session is isolated in the worktree /x/.claude/worktrees/y, but this command ' +
  'is too complex to verify that it stays inside the worktree. Refusing to run it — a worktree-isolated ' +
  "session's git operations must target its own worktree. Split it into plain, separate commands."
const STALE = 'GATE-0 stale-base ⛔ — HEAD is behind origin/main and your staged files overlap what ' +
  'already landed there. Sync, don’t bypass.'
const LOCK = 'Blocked: bare test-runner invocation. Re-run via `bin/test-lock -- <cmd>` to hold the ' +
  'per-repo test lock, or set CT_ALLOW_UNLOCKED_TESTS=1 to override.'
const PRIME = 'session_prime_gate: isolate + prime first — always start in a worktree, primed, before ' +
  'touching anything. Run /prime-core.'

test('each guard message maps to its reason_class', () => {
  expect(matchReason(WORKTREE)).toBe('worktree-path')
  expect(matchReason(STALE)).toBe('stale-base')
  expect(matchReason(LOCK)).toBe('test-lock')
  expect(matchReason(PRIME)).toBe('prime-gate')
})

test('empty or unrelated text is no match', () => {
  expect(matchReason('')).toBe(null)
  expect(matchReason('   ')).toBe(null)
  expect(matchReason('some unrelated guard-other refusal about plan interview')).toBe(null)
})

test('text echoing "stale-base" without the GATE-0 anchor is not misclassified', () => {
  expect(matchReason('refactor the stale-base guard module')).toBe(null)
})

test('a message with two anchors returns the higher-priority class deterministically', () => {
  // Contains both a stale-base anchor and a worktree anchor; priority order must be fixed.
  const both = 'GATE-0 stale-base ⛔ — also mentions target its own worktree somewhere'
  expect(matchReason(both)).toBe('stale-base')
})
