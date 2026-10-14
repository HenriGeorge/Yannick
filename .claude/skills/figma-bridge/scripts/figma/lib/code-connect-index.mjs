// code-connect-index.mjs — resolve DS components to their Figma node-ids from a project's
// Code Connect mappings (*.figma.tsx). Every figma.connect() call embeds the component's Figma
// node-id + fileKey, so the palette resolves a component → node-id with zero bridge cost (the
// whole-document get_local_components scan is unusable on large files). Pure, zero-dep.
// Ported from the Resonanz cg-figma pipeline (already generic).
//
// @typedef {{ name: string, nodeId: string, fileKey: string }} ConnectEntry
// @typedef {Record<string, { nodeId: string, fileKey: string }>} CodeConnectIndex

const CONNECT_URL = /figma\.com\/design\/([A-Za-z0-9]+)\/[^'"]*?node-id=(\d+)[-:](\d+)/
const FIRST_ARG = /figma\.connect\(\s*([A-Za-z0-9_]+)/

/**
 * Parse one `.figma.tsx` source into its Code Connect entry, or null if it has no figma.connect URL.
 * Name comes from the file basename (`Button.figma.tsx` → `Button`); if no path is given, falls back
 * to the first `figma.connect(<Component>, …)` argument.
 * @param {string} source
 * @param {string} [path]
 * @returns {ConnectEntry | null}
 */
export function parseConnect(source, path = '') {
  const m = source.match(CONNECT_URL)
  if (!m) return null
  const fileKey = m[1]
  const nodeId = `${m[2]}:${m[3]}` // Figma node-ids use ':'; Code Connect URLs encode it as '-'
  let name = ''
  const base = path.split('/').pop() || ''
  if (base.endsWith('.figma.tsx')) name = base.slice(0, -'.figma.tsx'.length)
  if (!name) { const a = source.match(FIRST_ARG); name = a ? a[1] : '' }
  if (!name) return null
  return { name, nodeId, fileKey }
}

/**
 * Reduce many `.figma.tsx` files to a name → {nodeId, fileKey} index. Unparseable files are skipped.
 * @param {{ path: string, content: string }[]} files
 * @returns {CodeConnectIndex}
 */
export function buildCodeConnectIndex(files) {
  /** @type {CodeConnectIndex} */
  const index = {}
  for (const f of files) {
    const r = parseConnect(f.content, f.path)
    if (r) index[r.name] = { nodeId: r.nodeId, fileKey: r.fileKey }
  }
  return index
}
