import { expect, test } from 'claude-code/testing'

// What Claude Code passes a ui.render hook for the band (props per the render-sites table).
const BAND = {
  plugin: 'gate-state',
  component: 'AbovePrompt',
  requestId: 'above-prompt',
  viewport: { columns: 100, rows: 30 },
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 3,
    bodyColumns: 80,
    scroll: { offset: 0, bodyRows: 3 },
    view: {},
  },
} as const

test('the band shows branch, worktree, port, and primed from the live signals', async ($, on) => {
  const cwd = '/work/.claude/worktrees/feat-x'

  // Answer each call the mod makes, in Claude Code's place.
  on('session.start', () => ({ cwd }))
  on('session.cwd', () => ({ value: cwd }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'feat-x\n', stderr: '' } }))
  on('fs.exists', () => ({ value: true }))
  on('fs.read', ($, e) => ({ value: e.path.endsWith('worktree.env') ? 'PORT=3214\n' : 'sess-123' }))
  // Stands for what other mods / Claude Code draw in the shared band (our `await next(e)`).
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['cc'] }))

  // Seed state (session.start doesn't run on its own in a test).
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'feat-x · wt:feat-x · :3214 · primed ✓' })).toBeDefined()
  await ui.unmount()
})

test('a primary checkout with no port shows primed ✗', async ($, on) => {
  const cwd = '/work/repo'

  on('session.start', () => ({ cwd }))
  on('session.cwd', () => ({ value: cwd }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'main\n', stderr: '' } }))
  on('fs.exists', () => ({ value: false }))
  on('fs.read', () => ({ value: '' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['cc'] }))

  await $.session.start({ surface: 'terminal', isInteractive: true, cwd })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'main · primary · primed ✗' })).toBeDefined()
  await ui.unmount()
})

test('the band preserves the upstream band content (next(e)) alongside its own line', async ($, on) => {
  const cwd = '/work/repo'

  on('session.start', () => ({ cwd }))
  on('session.cwd', () => ({ value: cwd }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: 'main\n', stderr: '' } }))
  on('fs.exists', () => ({ value: false }))
  on('fs.read', () => ({ value: '' }))
  // What another mod / Claude Code draws in the shared band — must survive our Box nesting.
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['upstream-band'] }))

  await $.session.start({ surface: 'terminal', isInteractive: true, cwd })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: 'upstream-band' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'main · primary · primed ✗' })).toBeDefined()
  await ui.unmount()
})

test('a git failure (non-zero exit) leaves the branch as ?', async ($, on) => {
  const cwd = '/work/repo'

  on('session.start', () => ({ cwd }))
  on('session.cwd', () => ({ value: cwd }))
  on('process.run', () => ({ value: { exitCode: 128, stdout: '', stderr: 'not a git repo' } }))
  on('fs.exists', () => ({ value: false }))
  on('fs.read', () => ({ value: '' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['cc'] }))

  await $.session.start({ surface: 'terminal', isInteractive: true, cwd })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: '? · primary · primed ✗' })).toBeDefined()
  await ui.unmount()
})

test('a cwd failure degrades visibly (? · ?) rather than freezing the band', async ($, on) => {
  const cwd = '/work/repo'

  on('session.start', () => ({ cwd }))
  // $.session.cwd() rejects in the mod — refresh must catch and show a degraded band.
  on('session.cwd', () => ({ deny: 'cwd unavailable' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['cc'] }))

  await $.session.start({ surface: 'terminal', isInteractive: true, cwd })

  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: '? · ? · primed ✗' })).toBeDefined()
  await ui.unmount()
})
