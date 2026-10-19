// gate-state: a band above the prompt showing this repo's GATE/worktree signals —
// branch · worktree · PORT · primed. Cheap LOCAL signals only (no git fetch): recomputed
// at session start and on each prompt submit; the band hook just reads the cached values.

let state = { branch: '?', worktree: 'primary', port: '', primed: false }

// Top-level so `claude plugin validate` sees the $ calls (passing $ to a top-level fn is allowed).
async function refresh($) {
  let cwd
  try {
    cwd = await $.session.cwd()
  } catch {
    // cwd unavailable — show a visibly degraded band, never a silently frozen one.
    state = { branch: '?', worktree: '?', port: '', primed: false }
    return
  }

  let branch = '?'
  try {
    const r = await $.process.run(['git', '-C', cwd, 'rev-parse', '--abbrev-ref', 'HEAD'])
    if (r.exitCode === 0) branch = r.stdout.trim() || '?'
  } catch { /* not a repo / git missing — leave '?' */ }

  // This repo's worktrees live under .claude/worktrees/<name>; anything else is the primary checkout.
  const m = cwd.match(/\/\.claude\/worktrees\/([^/]+)/)
  const worktree = m ? 'wt:' + m[1] : 'primary'

  let port = ''
  const envPath = cwd + '/.claude/worktree.env'
  try {
    if (await $.fs.exists(envPath)) {
      const pm = (await $.fs.read(envPath)).match(/^PORT=(\d+)/m)
      if (pm) port = ':' + pm[1]
    }
  } catch { /* unreadable — no port */ }

  let primed = false
  const primedPath = cwd + '/.claude/state/primed'
  try {
    if (await $.fs.exists(primedPath)) primed = (await $.fs.read(primedPath)).trim().length > 0
  } catch { /* unreadable — treat as not primed */ }

  state = { branch, worktree, port, primed }
}

export function register(on) {
  // Seed before the first prompt. .catch keeps a refresh failure from disrupting session start
  // (refresh already degrades visibly on its own; this is symmetric defense-in-depth).
  on('session.start', async ($, e, next) => {
    await refresh($)
    return next(e)
  }).catch(async ($, e, next) => next(e))

  // Branch / worktree / primed can change between turns — refresh and redraw on each submit.
  // .catch ensures a refresh error never blocks the prompt: pass it through unchanged.
  on('prompt.submit', async ($, e, next) => {
    await refresh($)
    $.ui.invalidate('ui.render')
    return next(e)
  }).catch(async ($, e, next) => next(e))

  // Draw the band. Keep what other mods draw there by nesting their result in our Box.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const { Box, Text } = $.ui.resolve(e)
    const theirs = await next(e)
    const line = [
      state.branch,
      state.worktree,
      ...(state.port ? [state.port] : []),
      'primed ' + (state.primed ? '✓' : '✗'),
    ].join(' · ')
    return Box({
      flexDirection: 'column',
      children: [theirs, Text({ dimColor: true, children: [line] })].filter(Boolean),
    })
  })
}
