// site-verify.mjs — GATE-2 acceptance for one built screen: read back the Figma frame's placed
// instances, evaluate the manifest's structural checklist against them, and (on pass) advance the
// manifest status to 'verified'. Optionally export to a PNG (--png). Config-driven generalization
// of the Resonanz cg-figma verify-screen.mjs. Reads only (no writes) unless --png. Zero-dep (relay).
//
//   node figma.mjs site-verify <screenId> [--png] [--config=<f>]
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { connect, join, rpc, close } from './relay-client.mjs'
import { evaluate } from './checklist.mjs'
import { routeToId, setStatus } from './manifest.mjs'
import { resolveSiteConfig } from './site-cli.mjs'

const WS_URL = process.env.FIGMA_WS_URL ?? 'ws://127.0.0.1:3055'
const WORK = resolve(process.cwd(), '.work')
const SCREENS = resolve(WORK, 'screens.json')
const MANIFEST = resolve(WORK, 'site-manifest.json')
const CAPTURES = resolve(WORK, 'captures')

export async function run(args) {
  const { cfg, CHANNEL } = resolveSiteConfig(args, 'site-verify', {})

  const screenId = args.find((a) => !a.startsWith('--'))
  if (!screenId) throw new Error('site-verify: name the screen id to verify')
  const doPng = args.includes('--png')

  if (!existsSync(SCREENS)) throw new Error(`site-verify: no ${SCREENS} — build the screen first`)
  if (!existsSync(MANIFEST)) throw new Error(`site-verify: no ${MANIFEST}`)
  const screens = JSON.parse(readFileSync(SCREENS, 'utf8'))
  const frameId = screens[screenId]?.frameId
  if (!frameId) throw new Error(`site-verify: no built frame for "${screenId}" in screens.json`)
  const manifest = JSON.parse(readFileSync(MANIFEST, 'utf8'))
  const id = routeToId(`/${screenId}`)
  const screen = manifest.screens[id] ?? manifest.screens[screenId]
  if (!screen) throw new Error(`site-verify: no manifest screen "${id}"`)
  const checklist = screen.structuralChecklist ?? []
  if (!checklist.length) throw new Error(`site-verify: screen "${id}" has an empty checklist — author it in the build spec`)

  function collectInstances(doc) {
    const out = []
    ;(function rec(n) { if (!n) return; if (n.type === 'INSTANCE') out.push(n.name); (n.children || []).forEach(rec) })(doc)
    return out
  }

  const conn = await connect(WS_URL)
  join(conn, CHANNEL)
  try {
    const doc = await rpc(conn, 'get_node_info', { nodeId: frameId }, 40000)
    const placed = collectInstances(doc)
    const result = evaluate(checklist, placed)
    console.log(`verify ${id} (frame ${frameId}) — placed instances: ${[...new Set(placed)].join(', ')}`)
    for (const item of result.items) console.log(`  ${item.present ? '✓' : '✗'} ${item.label}`)
    console.log(result.ok ? `PASS — ${result.items.length}/${result.items.length} checklist items present` : 'FAIL — missing items above')
    if (result.ok) {
      // setStatus throws on an illegal transition; a screen already at 'built'/'verified' re-running
      // verify is a legal no-op, so swallowing the same-state throw is the intended idempotency.
      try { setStatus(manifest, id, 'built') } catch { /* already at/past built */ }
      try { setStatus(manifest, id, 'verified') } catch { /* already verified */ }
      writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2))
      console.log(`manifest: ${id} → verified`)
    } else { process.exitCode = 1 }
    if (doPng) {
      const res = await rpc(conn, 'export_node_as_image', { nodeId: frameId, scale: 1, format: 'PNG' }, 60000)
      const buf = Buffer.from(res?.imageData ?? '', 'base64')
      if (buf.length === 0) throw new Error('export_node_as_image returned empty imageData')
      const out = resolve(CAPTURES, `${id}-built.png`)
      writeFileSync(out, buf)
      console.log(`png: ${out} (${buf.length} bytes)`)
    }
  } catch (e) { console.error('ERROR:', e.message); process.exitCode = 1 } finally { close(conn) }
}
