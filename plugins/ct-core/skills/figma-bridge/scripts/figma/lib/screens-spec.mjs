// screens-spec.mjs — data-only screen tree builders + a per-project screens JSON loader/validator.
// Pure, zero-dep. The builders (txt/comp/btn/col/row/rect) are ported from the Resonanz cg-figma
// build script; navItem + loadScreens are new (generalization). The build script's walk() consumes
// these node objects and issues the bridge calls — this module never touches the bridge.

export const txt = (text, size = 14, bold = false) => ({ text, size, bold })
export const comp = (name, extra = {}) => ({ component: name, ...extra })
export const btn = (label) => ({ component: 'Button', label })
const style = (o) => ({ bg: o.bg, border: o.border, radius: o.radius, weight: o.weight })
export const col = (name, children, o = {}) => ({ name, layout: { dir: 'VERTICAL', gap: o.gap ?? 16, align: o.align ?? 'MIN', justify: o.justify, pad: o.pad, wrap: o.wrap, ...style(o) }, children: children.filter(Boolean) })
export const row = (name, children, o = {}) => ({ name, layout: { dir: 'HORIZONTAL', gap: o.gap ?? 8, align: o.align ?? 'CENTER', justify: o.justify, pad: o.pad, wrap: o.wrap, ...style(o) }, children: children.filter(Boolean) })
export const rect = (name, height = 120, o = {}) => ({ rect: true, name, width: o.width ?? 300, height, bg: o.bg ?? '#f4f4f4' })

// navItem — the two-column sidebar recipe: an icon placeholder (small rect) + the label.
// Fixes the bare-text nav gap: real sidebars have an icon left of every item, but the bridge
// can't place real icon vectors, so a small rect stands in (exact glyphs would need per-icon DS
// components with node-ids, which aren't in the Code Connect index).
export const navItem = (label, o = {}) =>
  row(`nav:${label}`, [
    rect(`icon:${label}`, o.iconSize ?? 16, { width: o.iconSize ?? 16, bg: o.iconBg ?? '#d4d4d4' }),
    txt(label, o.size ?? 14),
  ], { gap: o.gap ?? 8, align: 'CENTER' })

/**
 * Unique `component` names referenced anywhere in a tree (for the palette check + checklist).
 * @param {object} tree
 * @returns {string[]}
 */
export function collectComponents(tree) {
  const out = new Set()
  ;(function rec(n) { if (!n) return; if (n.component) out.add(n.component); (n.children || []).forEach(rec) })(tree)
  return [...out]
}

/**
 * Validate a per-project screens map. Each screen needs a `tree`; every node must be either a leaf
 * (component/text/rect) or a layout frame (has `.layout`). Throws on an invalid node. Returns the
 * same object on success so callers can `const screens = loadScreens(JSON.parse(...))`.
 * @param {Record<string,{route:string,name:string,tree:object}>} json
 */
export function loadScreens(json) {
  const screens = json ?? {}
  for (const [id, s] of Object.entries(screens)) {
    if (!s || !s.tree) throw new Error(`screens-spec: screen "${id}" has no tree`)
    ;(function validate(n, path) {
      if (!n) return
      const isLeaf = n.component || n.text || n.rect
      if (!isLeaf && !n.layout) throw new Error(`screens-spec: invalid node at ${path} (neither a leaf nor a layout frame)`)
      ;(n.children || []).forEach((c, i) => validate(c, `${path}.children[${i}]`))
    })(s.tree, `${id}.tree`)
  }
  return screens
}
