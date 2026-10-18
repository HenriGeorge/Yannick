/**
 * Structural checklist evaluation for a built screen. Pure, zero-dep.
 * Ported from the Resonanz cg-figma pipeline (already generic).
 *
 * @typedef {{ label: string, present: boolean }} ChecklistItem
 * @typedef {{ items: ChecklistItem[], ok: boolean }} ChecklistResult
 */

/**
 * Evaluate a screen's placed-instance names against a structural checklist.
 *
 * An item is `present` iff some placed instance name contains the item's
 * needle: the `component:` tag (format `"label | component:Table"`) when
 * present, otherwise the full label matched as a case-insensitive substring.
 *
 * @param {string[]} checklist - checklist item labels (optionally `"... | component:Tag"`)
 * @param {string[]} placedInstanceNames - names of instances placed on the screen
 * @returns {ChecklistResult}
 */
export function evaluate(checklist, placedInstanceNames) {
  const placed = placedInstanceNames.map(n => n.toLowerCase())
  const items = checklist.map(label => {
    const tag = /component:(\S+)/.exec(label)
    const needle = (tag ? tag[1] : label).toLowerCase()
    const present = placed.some(n => n.includes(needle))
    return { label, present }
  })
  return { items, ok: items.every(i => i.present) }
}
