// Pure: given a reason_class and the denied command, produce a corrected command (or canonical
// guidance). Conservative by default — when a safe correction can't be derived, return the guidance
// line (never a fabricated command the model would run trustingly).

import type { ReasonClass } from './match.js'

export const GUIDANCE: Record<ReasonClass, string> = {
  'worktree-path':
    'Run each command separately as plain, unchained commands from the worktree root — no `cd`, no `&&`, no env-prefix. For a `gh` PR/issue body, write it to a file and use --body-file.',
  'stale-base':
    'Sync, don’t bypass: `git merge origin/main` (a merge commit on a pushed branch; never force-push), then re-run.',
  'test-lock':
    'Hold the per-repo lock: re-run under `bin/test-lock --wait -- <cmd>`.',
  'prime-gate':
    'Enter your own worktree and prime first: run `/prime-core` (EnterWorktree first if not already in one).',
}

function quotesBalanced(s: string): boolean {
  return (s.match(/"/g) ?? []).length % 2 === 0 && (s.match(/'/g) ?? []).length % 2 === 0
}

function splitCompound(command: string): string | null {
  if (!quotesBalanced(command)) return null
  const rawSegments = command.split('&&').map(s => s.trim()).filter(Boolean)
  // If `&&` fell inside a quoted string, a segment's quotes are unbalanced — unsafe to split.
  if (rawSegments.some(s => !quotesBalanced(s))) return null
  const segments = rawSegments.filter(s => !/^cd\s+\S+$/.test(s)) // drop a leading `cd <path>`
  return segments.length >= 2 ? segments.join('\n') : null
}

export function deriveFix(reason: ReasonClass, command: string): string {
  switch (reason) {
    case 'worktree-path':
      return splitCompound(command) ?? GUIDANCE['worktree-path']
    case 'stale-base':
      return GUIDANCE['stale-base']
    case 'test-lock':
      // Don't double-wrap an already-locked command, and don't emit a dangling prefix.
      return command.trim() && !command.includes('test-lock')
        ? `bin/test-lock --wait -- ${command}`
        : GUIDANCE['test-lock']
    case 'prime-gate':
      return GUIDANCE['prime-gate']
  }
}
