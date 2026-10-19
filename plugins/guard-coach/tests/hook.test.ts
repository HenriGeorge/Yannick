import { expect, mock, test } from 'claude-code/testing'

const WT = 'Refusing to run it — a worktree-isolated session’s git operations must target its own worktree.'
const STALE = 'GATE-0 stale-base ⛔ — HEAD is behind origin/main and your staged files overlap.'
const OTHER = 'Blocked: plan interview required before this plan commit (guard-other).'

function stubs(on: (name: string, ...a: unknown[]) => unknown) {
  mock.store(on, {})
  on('prompt.fill', () => ({ isFilled: true }))
}

test('a worktree-path error is augmented with a CORRECTED split command', async ($, on) => {
  stubs(on)
  on('tool.call', () => ({ isError: true, result: WT, text: WT }))
  const r = await $.tool.call({ tool: 'Bash', command: 'cd /x && git status && git log' })
  expect(r.text).toContain('CORRECTED:')
  expect(r.text).toContain('git status')
  expect(r.isError).toBe(true)
})

test('a stale-base error is augmented with the merge-origin snippet', async ($, on) => {
  stubs(on)
  on('tool.call', () => ({ isError: true, result: STALE, text: STALE }))
  const r = await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
  expect(r.text).toContain('git merge origin/main')
})

test('an out-of-scope error passes through untouched', async ($, on) => {
  stubs(on)
  on('tool.call', () => ({ isError: true, result: OTHER, text: OTHER }))
  const r = await $.tool.call({ tool: 'Bash', command: 'git commit -m x' })
  expect(r.text).toBe(OTHER)
  expect(r.text).not.toContain('CORRECTED:')
})

test('a successful (non-error) result passes through', async ($, on) => {
  stubs(on)
  on('tool.call', () => ({ result: 'ok' }))
  const r = await $.tool.call({ tool: 'Bash', command: 'ls' })
  expect(r.result).toBe('ok')
})

test('a non-string text is handled defensively (no crash, no CORRECTED)', async ($, on) => {
  stubs(on)
  on('tool.call', () => ({ isError: true, result: 'x', text: 12345 }))
  const r = await $.tool.call({ tool: 'Bash', command: 'x' })
  expect(r.text).toBe(12345)
})

test('a huge text skips the append (stays within the deny cap) without crashing', async ($, on) => {
  stubs(on)
  const huge = WT + ' ' + 'x'.repeat(5000)
  on('tool.call', () => ({ isError: true, result: huge, text: huge }))
  const r = await $.tool.call({ tool: 'Bash', command: 'cd /x && git a && git b' })
  expect(r.text).toBe(huge)
  expect(r.text).not.toContain('CORRECTED:')
})

test('the /improve nudge appears once across repeated worktree-path errors, not every time', async ($, on) => {
  stubs(on)
  on('tool.call', () => ({ isError: true, result: WT, text: WT }))
  const texts: string[] = []
  for (let i = 0; i < 3; i++) {
    const r = await $.tool.call({ tool: 'Bash', command: 'cd /x && git a && git b' })
    texts.push(r.text)
  }
  const nudged = texts.filter(t => t.includes('/improve')).length
  expect(nudged).toBe(1)
})
