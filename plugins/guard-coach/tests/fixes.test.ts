import { expect, test } from 'claude-code/testing'
import { deriveFix, GUIDANCE } from '../hooks/fixes.js'

test('worktree-path splits a compound git into separate plain commands, dropping leading cd', () => {
  const fix = deriveFix('worktree-path', 'cd /x && git status --short && git log --oneline -1')
  expect(fix).toContain('git status --short')
  expect(fix).toContain('git log --oneline -1')
  expect(fix).not.toContain('&&')
  expect(fix).not.toMatch(/\bcd\b/)
})

test('worktree-path with nothing to split falls back to the guidance line, not a fabricated command', () => {
  expect(deriveFix('worktree-path', 'git status')).toBe(GUIDANCE['worktree-path'])
})

test('worktree-path with unbalanced quotes is unsafe to split → guidance', () => {
  expect(deriveFix('worktree-path', 'cd /x && echo "a && b')).toBe(GUIDANCE['worktree-path'])
})

test('stale-base returns the merge-origin sync snippet', () => {
  expect(deriveFix('stale-base', 'git commit -m x')).toContain('git merge origin/main')
})

test('test-lock re-prefixes the original command with --wait', () => {
  expect(deriveFix('test-lock', 'bash tests/run.sh')).toBe('bin/test-lock --wait -- bash tests/run.sh')
})

test('prime-gate points at /prime-core', () => {
  expect(deriveFix('prime-gate', 'git commit -m x')).toContain('/prime-core')
})

test('worktree-path with && inside quotes is unsafe to split → guidance', () => {
  expect(deriveFix('worktree-path', 'git commit -m "a && b" && git push')).toBe(GUIDANCE['worktree-path'])
})

test('worktree-path with a ; or || operator is unsafe to split → guidance', () => {
  expect(deriveFix('worktree-path', 'cd /x && git a ; git b')).toBe(GUIDANCE['worktree-path'])
})

test('test-lock with an empty command → guidance (no dangling prefix)', () => {
  expect(deriveFix('test-lock', '')).toBe(GUIDANCE['test-lock'])
})

test('test-lock on an already-wrapped command → guidance (no double-wrap)', () => {
  expect(deriveFix('test-lock', 'bin/test-lock -- bash tests/run.sh')).toBe(GUIDANCE['test-lock'])
})
