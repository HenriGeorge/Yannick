// site-palette.mjs — resolve a project's DS components into a hidden __SITE_PALETTE__ frame of
// REAL instances, and cache name → {nodeId, instanceNodeId}. Later screen builds clone from the
// cache. Config-driven generalization of the Resonanz cg-figma figma-palette.mjs.
//
// Resolution = the project's Code Connect index (cfg.uiDir/*.figma.tsx) → create_component_instance
// with the `componentId` (node-id) path (O(1) getNodeByIdSafe in the patched plugin — NO
// whole-document scan, NO page navigation; get_local_components is unusable on large files).
// Zero-dep (relay only). Requires Figma FOREGROUNDED.
//
//   node figma.mjs site-palette <Component...> [--config=<f>]
import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { connect, join, rpc, close } from './relay-client.mjs'
import { buildCodeConnectIndex } from './code-connect-index.mjs'
import { resolveSiteConfig } from './site-cli.mjs'

const WS_URL = process.env.FIGMA_WS_URL ?? 'ws://127.0.0.1:3055'
const CACHE = resolve(process.cwd(), '.work', 'palette-cache.json')

export async function run(args) {
  const { cfg, CHANNEL } = resolveSiteConfig(args, 'site-palette', { requirePage: true })

  const uiDir = resolve(process.cwd(), cfg.uiDir)
  if (!existsSync(uiDir)) throw new Error(`site-palette: uiDir ${uiDir} not found — rebuild needs a DS with Code Connect (*.figma.tsx). Use snapshot mode instead, or add Code Connect.`)
  const files = readdirSync(uiDir).filter((f) => f.endsWith('.figma.tsx')).map((f) => ({ path: `${cfg.uiDir}/${f}`, content: readFileSync(resolve(uiDir, f), 'utf8') }))
  const index = buildCodeConnectIndex(files)
  if (!Object.keys(index).length) throw new Error(`site-palette: no Code Connect mappings in ${uiDir} — rebuild needs *.figma.tsx. Use snapshot mode, or add Code Connect.`)

  const requested = args.filter((a) => !a.startsWith('--'))
  const prior = existsSync(CACHE) ? JSON.parse(readFileSync(CACHE, 'utf8')) : {}
  // ADDITIVE: re-instance the UNION of previously-cached and newly requested components (the old
  // palette frame is deleted each run, so a subset call must not drop earlier entries).
  const wanted = [...new Set([...Object.keys(prior.components || {}), ...requested])]
  if (!wanted.length) throw new Error('site-palette: name at least one component, e.g. site-palette Button Table')

  const conn = await connect(WS_URL)
  join(conn, CHANNEL)
  const out = { _page: cfg.canvasPage, _paletteFrameId: null, components: {} }
  try {
    if (prior._paletteFrameId) { try { await rpc(conn, 'delete_node', { nodeId: prior._paletteFrameId }, 20000) } catch (e) { console.error(`prior-palette delete (continuing): ${e.message}`) } }
    const frame = await rpc(conn, 'create_frame', { name: '__SITE_PALETTE__', parentId: cfg.canvasPage, x: -6000, y: -6000, width: Math.max(260 * wanted.length, 260), height: 320 }, 30000)
    out._paletteFrameId = frame.id
    console.log(`palette frame ${frame.id} on page ${cfg.canvasPage}`)
    const missing = []
    let i = 0
    for (const name of wanted) {
      const entry = index[name]
      if (!entry) { console.error(`  ✗ ${name}: not in Code Connect index`); missing.push(name); continue }
      try {
        const inst = await rpc(conn, 'create_component_instance', { componentId: entry.nodeId, parentId: frame.id, x: i * 260, y: 0 }, 30000)
        out.components[name] = { nodeId: entry.nodeId, instanceNodeId: inst.id, name: inst.name } // rendered name for checklist match
        console.log(`  ✓ ${name} → ${inst.id} (${inst.name})`)
        i++
      } catch (e) { console.error(`  ✗ ${name}: ${e.message}`); missing.push(name) }
    }
    writeFileSync(CACHE, JSON.stringify(out, null, 2))
    console.log(`palette: ${Object.keys(out.components).length}/${wanted.length} instances; cache ${CACHE}`)
    if (missing.length) { console.error(`MISSING (fail loud): ${missing.join(', ')}`); process.exitCode = 1 }
  } catch (e) { console.error('ERROR:', e.message); process.exitCode = 1 } finally { close(conn) }
}
