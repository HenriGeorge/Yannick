// site-build.mjs — assemble screens from a per-project screens JSON: nested auto-layout frames
// with cloned DS instances at the leaves. Config-driven generalization of the Resonanz cg-figma
// figma-build-screen.mjs; the hardcoded SCREENS_SPEC is replaced by cfg.screensSpec (validated by
// loadScreens), and --theme threads token colors through the tree. Zero-dep (relay only).
// Requires Figma FOREGROUNDED. Leaves clone from the palette cache by instanceNodeId (O(1)).
//
//   node figma.mjs site-build <screenId|all> [screenId...] [--theme=light|dark|auto] [--config=<f>]
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { connect, join, rpc, close } from './relay-client.mjs'
import { resolveSiteConfig } from './site-cli.mjs'
import { loadScreens, collectComponents } from './screens-spec.mjs'
import { setStatus, upsertScreen, routeToId, routeToPageName } from './manifest.mjs'
import { themeFor } from './theme.mjs'

const WS_URL = process.env.FIGMA_WS_URL ?? 'ws://127.0.0.1:3055'
const WORK = resolve(process.cwd(), '.work')
const CACHE = resolve(WORK, 'palette-cache.json')
const SCREENS = resolve(WORK, 'screens.json')
const MANIFEST = resolve(WORK, 'site-manifest.json')

function hexRgba(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '')
  if (!m) throw new Error(`build: bad hex "${hex}" (want #rrggbb)`)
  return { r: parseInt(m[1], 16) / 255, g: parseInt(m[2], 16) / 255, b: parseInt(m[3], 16) / 255, a: 1 }
}

export async function run(args) {
  const { cfg, CHANNEL, get } = resolveSiteConfig(args, 'site-build', { requirePage: true })

  const specPath = resolve(process.cwd(), cfg.screensSpec || '.work/screens-spec.json')
  if (!existsSync(specPath)) throw new Error(`site-build: no screens spec at ${specPath} (set cfg.screensSpec)`)
  const SCREENS_SPEC = loadScreens(JSON.parse(readFileSync(specPath, 'utf8')))

  const requested = args.filter((a) => !a.startsWith('--'))
  if (!requested.length) throw new Error(`site-build: name a screen or 'all'. screens: ${Object.keys(SCREENS_SPEC).join(', ')}`)
  const screenIds = requested.includes('all') ? Object.keys(SCREENS_SPEC) : requested
  for (const r of screenIds) if (!SCREENS_SPEC[r]) throw new Error(`no spec for "${r}"`)

  if (!existsSync(CACHE)) throw new Error(`site-build: no ${CACHE} — run site-palette first`)
  const cache = JSON.parse(readFileSync(CACHE, 'utf8'))
  const CANVAS_PAGE = cache._page
  const instanceOf = (name) => {
    const id = cache.components?.[name]?.instanceNodeId
    if (!id) throw new Error(`palette has no instance for "${name}" — add it via site-palette ${name}`)
    return id
  }

  // Theme: --theme overrides cfg.theme; auto uses the captured bg sample from the manifest.
  const manifest = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : { screens: {}, meta: {} }
  const themeMode = get('theme') ?? cfg.theme
  const tokens = themeFor(themeMode, manifest.meta?.sampleBg)

  const conn = await connect(WS_URL)
  join(conn, CHANNEL)

  function collectText(doc) { const out = []; (function rec(n) { if (!n) return; if (n.type === 'TEXT') out.push(n); (n.children || []).forEach(rec) })(doc); return out }
  async function applyText(cloneId, node) {
    try {
      const doc = await rpc(conn, 'get_node_info', { nodeId: cloneId }, 30000)
      const texts = collectText(doc)
      if (node.label) {
        if (texts[0]) await rpc(conn, 'set_text_content', { nodeId: texts[0].id, text: node.label }, 30000)
        else console.error(`  (label NOT applied ${node.component}="${node.label}": no text layer)`)
      }
      if (node.title) {
        const t = texts.find((x) => /table title/i.test(x.characters || '')) || texts[0]
        if (t) await rpc(conn, 'set_text_content', { nodeId: t.id, text: node.title }, 30000)
        else console.error(`  (title NOT applied ${node.component}="${node.title}": no text layer)`)
      }
    } catch (e) { console.error(`  (text override skip ${node.component}: ${e.message})`) }
  }

  async function walk(node, parentId) {
    if (node.component) {
      const r = await rpc(conn, 'clone_node', { nodeId: instanceOf(node.component), parentId }, 30000)
      if (node.label || node.title) await applyText(r.id, node)
      return
    }
    if (node.text) {
      const r = await rpc(conn, 'create_text', { parentId, text: node.text, fontSize: node.size ?? 14, fontWeight: node.bold ? 700 : 400, name: node.text.slice(0, 24) }, 30000)
      try { await rpc(conn, 'set_fill_color', { nodeId: r.id, color: hexRgba(tokens.text) }, 20000) } catch (e) { console.error(`  (text color skipped "${node.text.slice(0, 24)}": ${e.message})`) }
      return
    }
    if (node.rect) { await rpc(conn, 'create_rectangle', { parentId, x: 0, y: 0, width: node.width ?? 300, height: node.height ?? 120, name: node.name ?? 'rect', fillColor: hexRgba(node.bg) }, 30000); return }
    const f = await rpc(conn, 'create_frame', { parentId, x: 0, y: 0, width: 400, height: 100, name: node.name ?? 'frame' }, 30000)
    const L = node.layout
    await rpc(conn, 'set_auto_layout', {
      nodeId: f.id, layoutMode: L.dir, itemSpacing: L.gap ?? 0,
      paddingTop: L.pad ?? 0, paddingBottom: L.pad ?? 0, paddingLeft: L.pad ?? 0, paddingRight: L.pad ?? 0,
      layoutWrap: L.wrap ? 'WRAP' : 'NO_WRAP',
      ...(L.justify ? { primaryAxisAlignItems: L.justify } : {}), ...(L.align ? { counterAxisAlignItems: L.align } : {}),
    }, 30000)
    // Styling: explicit spec bg/border win; otherwise themed frames (border set) take token colors.
    if (L.bg) await rpc(conn, 'set_fill_color', { nodeId: f.id, color: hexRgba(L.bg) }, 30000)
    else if (L.themed) await rpc(conn, 'set_fill_color', { nodeId: f.id, color: hexRgba(tokens.cardBg) }, 30000)
    if (L.border || L.themed) await rpc(conn, 'set_stroke_color', { nodeId: f.id, color: hexRgba(L.border ?? tokens.border), strokeWeight: L.weight ?? 1 }, 30000)
    if (L.radius) await rpc(conn, 'set_corner_radius', { nodeId: f.id, radius: L.radius }, 30000)
    for (const child of node.children) await walk(child, f.id)
    return f
  }

  const screensState = existsSync(SCREENS) ? JSON.parse(readFileSync(SCREENS, 'utf8')) : {}
  const COLS = 5, COLW = 1100, ROWH = 1800, BASE_X = -16000
  const built = [], failed = []
  try {
    for (let i = 0; i < screenIds.length; i++) {
      const rid = screenIds[i]
      const spec = SCREENS_SPEC[rid]
      const x = BASE_X + (i % COLS) * COLW
      const y = Math.floor(i / COLS) * ROWH
      try {
        if (screensState[rid]?.frameId) { try { await rpc(conn, 'delete_node', { nodeId: screensState[rid].frameId }, 20000) } catch (e) { console.error(`  prior ${rid} delete (continuing): ${e.message}`) } }
        // De-CG: the screen's display name comes from the config prefix (routeToPageName), not a
        // baked-in spec name; the spec's own name is the fallback when no prefix is configured.
        const screenName = cfg.pageNamePrefix ? routeToPageName(spec.route, cfg.pageNamePrefix) : spec.name
        const root = await rpc(conn, 'create_frame', { parentId: CANVAS_PAGE, x, y, width: 900, height: 600, name: screenName }, 30000)
        const L = spec.tree.layout
        await rpc(conn, 'set_auto_layout', {
          nodeId: root.id, layoutMode: L.dir, itemSpacing: L.gap ?? 0,
          paddingTop: L.pad ?? 0, paddingBottom: L.pad ?? 0, paddingLeft: L.pad ?? 0, paddingRight: L.pad ?? 0,
          ...(L.align ? { counterAxisAlignItems: L.align } : {}),
        }, 30000)
        await rpc(conn, 'set_fill_color', { nodeId: root.id, color: hexRgba(L.bg ?? tokens.cardBg) }, 30000) // root bg = theme
        for (const child of spec.tree.children) await walk(child, root.id)
        screensState[rid] = { frameId: root.id, name: screenName }
        writeFileSync(SCREENS, JSON.stringify(screensState, null, 2))
        const comps = collectComponents(spec.tree)
        const checklist = comps.map((c) => `${c} | component:${cache.components?.[c]?.name ?? c}`)
        upsertScreen(manifest, { route: spec.route, label: spec.route, section: routeToId(spec.route), referencePng: `.work/captures/${rid}.png`, structuralChecklist: checklist })
        const id = routeToId(spec.route)
        try { setStatus(manifest, id, 'mapped') } catch { /* past */ }
        try { setStatus(manifest, id, 'built') } catch { /* past */ }
        writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2))
        console.log(`✓ ${rid} → ${root.id}`)
        built.push(rid)
      } catch (e) { console.error(`✗ ${rid}: ${e.message}`); failed.push(rid) }
    }
    console.log(`built ${built.length}/${screenIds.length} (theme ${themeMode})${failed.length ? `; FAILED: ${failed.join(', ')}` : ''}`)
    if (failed.length) process.exitCode = 1
  } catch (e) { console.error('ERROR:', e.message); process.exitCode = 1 } finally { close(conn) }
}
