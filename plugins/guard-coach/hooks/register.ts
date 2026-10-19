import type { On } from 'claude-code'

import { deriveFix } from './fixes.js'
import { matchReason } from './match.js'

const COUNT_THRESHOLD = 3
const CAP = 3500 // keep the augmented text clear of the ~4096-char deny/error cap

/**
 * When a known guard denies a Bash call, the refusal comes back as a failed call
 * (`r.isError === true`, the guard message in `r.text` — Task-0 ruling, not `r.deny`).
 * guard-coach recognizes it, appends a CORRECTED command the model can retry from, pre-fills the
 * human prompt box, and nudges /improve once a reason recurs. Fail-open throughout: it only ever
 * rewrites the *message* of an already-failed call — never un-denies, never blocks.
 */
export function register(on: On): void {
  const told = new Set<string>() // per-session nudge dedupe

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const r = await next(e)
    if (!r || r.isError !== true || typeof r.text !== 'string') return r

    const reason = matchReason(r.text)
    if (!reason) return r
    if (r.text.length > CAP) return r // too close to the cap — leave the guard message as-is

    const fix = deriveFix(reason, typeof e.command === 'string' ? e.command : '')
    let text = r.text + '\n\nCORRECTED: ' + fix

    // Recurrence counter (best-effort) → one /improve nudge per reason per session.
    try {
      const key = 'count:' + reason
      const n = ((await $.store.get(key)) as number | undefined) ?? 0
      await $.store.set(key, n + 1)
      if (n + 1 >= COUNT_THRESHOLD && !told.has(reason)) {
        told.add(reason)
        text += `\n(guard-coach: hit ${reason} ${n + 1}× this session — consider /improve)`
      }
    } catch {
      /* counter is best-effort; never lose the CORRECTED line over it */
    }

    // Human lane (best-effort; may no-op outside a prompt context).
    try {
      await $.prompt.fill({ text: fix.split('\n')[0] })
    } catch {
      /* secondary lane */
    }

    return { ...r, text }
  }).catch(async ($, e, next) => next(e))
}
