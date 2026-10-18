// routes.mjs — same-origin pathname extraction from scraped hrefs (augments routes.txt).
// Pure, zero-dep. Ported from the Resonanz cg-figma pipeline (already generic).
export function extractRoutes(hrefs, origin) {
  const out = new Set()
  for (const h of hrefs) {
    let u
    try { u = new URL(h, origin) } catch { continue }
    if (!/^https?:$/.test(u.protocol)) continue
    if (u.origin !== origin) continue
    out.add(u.pathname)
  }
  return [...out].sort()
}
