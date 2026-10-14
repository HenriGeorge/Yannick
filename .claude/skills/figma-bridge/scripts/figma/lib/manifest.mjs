// manifest.mjs — screen state machine for the site-to-figma pipeline. Pure, zero-dep.
// Ported from the Resonanz cg-figma pipeline; the only de-CG change is routeToPageName's
// hardcoded "CG ·" prefix becoming a caller-supplied, default-empty prefix.
const ORDER = ['captured', 'mapped', 'built', 'verified']

/**
 * @typedef {'captured'|'mapped'|'built'|'verified'} Status
 * @typedef {Object} Screen
 * @property {string} id
 * @property {string} route
 * @property {string} label
 * @property {string} section
 * @property {string} referencePng
 * @property {string[]} structuralChecklist
 * @property {Status} status
 * @typedef {{screens: Record<string, Screen>}} Manifest
 */

/**
 * @param {string} route
 * @returns {string}
 */
export function routeToId(route) {
  const slug = route.replace(/^\/+/, '').replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '')
  return slug || 'home'
}
/**
 * Page name for a route. Prefix is caller-supplied (de-CG: was a hardcoded "CG ·").
 * @param {string} route
 * @param {string} [prefix]
 * @returns {string}
 */
export function routeToPageName(route, prefix = '') {
  const base = route.replace(/^\/+/, '') || 'home'
  return prefix ? `${prefix} · ${base}` : base
}
/** @returns {Manifest} */
export function emptyManifest() { return { screens: {} } }

/**
 * @param {Manifest} m
 * @param {{route: string, label: string, section: string, referencePng: string, structuralChecklist?: string[]}} entry
 * @returns {Manifest}
 */
export function upsertScreen(m, { route, label, section, referencePng, structuralChecklist }) {
  const id = routeToId(route)
  const prev = m.screens[id]
  m.screens[id] = {
    id, route, label, section, referencePng,
    structuralChecklist: structuralChecklist ?? prev?.structuralChecklist ?? [],
    status: prev?.status ?? 'captured',
  }
  return m
}
/**
 * @param {Manifest} m
 * @param {string} id
 * @param {Status} status
 * @returns {Manifest}
 */
export function setStatus(m, id, status) {
  const s = m.screens[id]
  if (!s) throw new Error(`unknown screen: ${id}`)
  const from = ORDER.indexOf(s.status), to = ORDER.indexOf(status)
  if (to < 0) throw new Error(`invalid status: ${status}`)
  if (to !== from + 1 && to !== from) throw new Error(`illegal transition ${s.status} -> ${status}`)
  s.status = status
  return m
}
