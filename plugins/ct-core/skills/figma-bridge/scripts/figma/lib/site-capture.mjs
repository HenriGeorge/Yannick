// site-capture.mjs — site-to-figma: auth + full-page crawl of N routes → PNGs + manifest.
// Config-driven generalization of the Resonanz cg-figma capture-cg.mjs. Playwright is imported
// LAZILY inside run() (capture family) so dispatching a core subcommand needs no `npm install`.
//
//   node figma.mjs site-capture --login [--config=<f>]        headed; you log in, storageState → .work/auth.json
//   node figma.mjs site-capture --from-session [--config=<f>] build auth.json from a console export (.work/site-session.json)
//   node figma.mjs site-capture [--routes=<f>] [--max=N] [--route=/x] [--config=<f>]   crawl with saved auth
//
// Auth/captures/manifest live under the invoking project's .work/ (gitignored). Routes come
// PRIMARILY from a hand-maintained routes.txt; anchor scraping only AUGMENTS it (a React SPA may
// expose few/no <a href> anchors).
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { loadConfig } from './site-config.mjs'
import { buildStorageState } from './auth.mjs'
import { extractRoutes } from './routes.mjs'
import { emptyManifest, upsertScreen, routeToId } from './manifest.mjs'

const WORK = resolve(process.cwd(), '.work')
const AUTH = resolve(WORK, 'auth.json')
const CAPTURES = resolve(WORK, 'captures')
const MANIFEST = resolve(WORK, 'site-manifest.json')
const SESSION = resolve(WORK, 'site-session.json')

function parseArgs(args) {
  const get = (name) => {
    const hit = args.find((a) => a === `--${name}` || a.startsWith(`--${name}=`))
    if (!hit) return undefined
    const eq = hit.indexOf('=')
    return eq === -1 ? true : hit.slice(eq + 1)
  }
  return get
}
function readConfig(get) {
  const path = typeof get('config') === 'string' ? get('config') : resolve(process.cwd(), 'site-to-figma.config.json')
  if (!existsSync(path)) throw new Error(`site-capture: no config at ${path} (copy site-to-figma.config.example.json)`)
  return loadConfig(JSON.parse(readFileSync(path, 'utf8')))
}
function ensureDir(p) { mkdirSync(p, { recursive: true }) }
// Self-contained protection: `.work/` holds live auth (storageState incl. httpOnly cookies, console
// exports with session tokens). The docs claim it's gitignored, so make that true regardless of the
// consumer repo's .gitignore — drop a `.work/.gitignore` of `*` on first write (R6). Exported for test.
export function ensureWorkIgnore(work) {
  const gi = resolve(work, '.gitignore')
  if (!existsSync(gi)) writeFileSync(gi, '*\n')
}
function sectionOf(route) { return route.replace(/^\/+/, '').split('/')[0] || 'root' }

// A completed login = a non-noise cookie on the auth domain, or localStorage on the origin.
const NOISE_COOKIE = /^(_ga|_ga_|g_state$|__stripe_|m$)/
function isAuthed(state, authDomain) {
  const domainRe = new RegExp(authDomain.replace(/\./g, '\\.') + '$')
  const realCookie = (state.cookies || []).some((c) => domainRe.test(c.domain) && !NOISE_COOKIE.test(c.name))
  const hasLocalStorage = (state.origins || []).some((o) => domainRe.test(new URL(o.origin).hostname) && (o.localStorage || []).length > 0)
  return realCookie || hasLocalStorage
}

// rgb()/rgba() → #rrggbb (for --theme=auto background sampling); null when transparent/unknown.
function rgbToHex(s) {
  const m = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)/.exec(s || '')
  if (!m) return null
  if (m[4] !== undefined && Number(m[4]) === 0) return null // transparent
  return '#' + [m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join('')
}

async function login(cfg) {
  const { chromium } = await import('playwright')
  ensureDir(WORK); ensureWorkIgnore(WORK)
  const browser = await chromium.launch({ headless: false, args: ['--start-maximized', '--new-window'] })
  const context = await browser.newContext({ viewport: null })
  const page = await context.newPage()
  let disconnected = false
  browser.on('disconnected', () => { disconnected = true })
  await page.goto(cfg.origin, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch((e) => console.error(`initial goto failed (navigate manually): ${e.message}`))
  await page.bringToFront().catch(() => {})
  console.log(`A Chromium window is open. Log in to ${cfg.origin}.`)
  console.log('I auto-detect a completed login and finish on my own — you can also just close the window.')
  const deadline = Date.now() + 900000
  let dumps = 0, authedStreak = 0
  while (!disconnected && Date.now() < deadline) {
    try {
      const state = await context.storageState({ path: AUTH }); dumps++
      authedStreak = isAuthed(state, cfg.authDomain) ? authedStreak + 1 : 0
      if (authedStreak >= 2) { console.log('detected a completed login — finishing.'); break }
    } catch { /* mid-navigation */ }
    await page.waitForTimeout(3000).catch(() => {})
  }
  if (!disconnected) { try { await context.storageState({ path: AUTH }) } catch {} }
  await browser.close().catch(() => {})
  if (!existsSync(AUTH)) throw new Error('no auth.json written — login did not complete')
  const state = JSON.parse(readFileSync(AUTH, 'utf8'))
  console.log(`saved ${AUTH} (${dumps} dumps, ${state.cookies?.length ?? 0} cookies, ${state.origins?.length ?? 0} origins).`)
  if (!isAuthed(state, cfg.authDomain)) throw new Error('no session detected (only analytics/SSO-state cookies) — re-run --login and finish sign-in')
  console.log('✓ session detected.')
}

// Reuse the figma-bridge `auth` buildStorageState for the console-export path (DRY).
function fromSession(cfg) {
  if (!existsSync(SESSION)) throw new Error(`site-capture: no ${SESSION} — paste the browser-console export there first`)
  const state = buildStorageState(JSON.parse(readFileSync(SESSION, 'utf8')))
  ensureDir(WORK); ensureWorkIgnore(WORK)
  writeFileSync(AUTH, JSON.stringify(state, null, 2))
  if (!isAuthed(state, cfg.authDomain)) throw new Error('export has no session cookie/localStorage for the auth domain — not authenticated')
  console.log(`✓ built ${AUTH}: ${state.cookies.length} cookies, ${state.origins[0]?.localStorage.length ?? 0} localStorage`)
}

function resolveRoutes(cfg, get, scraped) {
  const routes = new Set(['/'])
  const routesFile = typeof get('routes') === 'string' ? get('routes') : (cfg.routesFile && resolve(process.cwd(), cfg.routesFile))
  if (routesFile && existsSync(routesFile)) {
    for (const line of readFileSync(routesFile, 'utf8').split('\n')) {
      const t = line.trim()
      if (t && !t.startsWith('#')) routes.add(t.startsWith('/') ? t : `/${t}`)
    }
  }
  for (const r of scraped) routes.add(r)
  const single = get('route')
  if (typeof single === 'string') return [single.startsWith('/') ? single : `/${single}`]
  return [...routes].sort()
}

async function crawl(cfg, get) {
  if (!existsSync(AUTH)) throw new Error(`site-capture: no ${AUTH} — run --login or --from-session first`)
  const { chromium } = await import('playwright')
  ensureDir(CAPTURES); ensureWorkIgnore(WORK)
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ storageState: AUTH, viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  await page.goto(cfg.origin, { waitUntil: 'load', timeout: 45000 }).catch((e) => console.error(`landing goto: ${e.message}`))
  await page.waitForTimeout(2500)
  // Fail loud if the saved session expired: isAuthed is enforced at save time, but a stale auth.json
  // would otherwise capture logged-out/login pages as if they were real screens (silent wrong output).
  const live = await context.storageState()
  if (!isAuthed(live, cfg.authDomain)) throw new Error('site-capture: saved auth is not authenticated against the live site (session expired?) — re-run site-capture --login; refusing to capture a logged-out session')
  const hrefs = await page.$$eval('a[href]', (els) => els.map((e) => e.href)).catch((e) => { console.error(`anchor scrape failed (routes.txt only): ${e.message}`); return [] })
  const scraped = extractRoutes(hrefs, cfg.origin)
  const manifest = existsSync(MANIFEST) ? JSON.parse(readFileSync(MANIFEST, 'utf8')) : emptyManifest()
  if (!manifest.meta) manifest.meta = {}
  const routes = resolveRoutes(cfg, get, scraped)
  const max = Number(get('max')) || routes.length
  const targets = routes.slice(0, max)
  console.log(`routes: ${routes.length} (${scraped.length} scraped) → capturing ${targets.length}`)
  const captured = []
  for (const route of targets) {
    const id = routeToId(route)
    const png = resolve(CAPTURES, `${id}.png`)
    try {
      await page.goto(cfg.origin + route, { waitUntil: 'load', timeout: 45000 })
      await page.waitForTimeout(2500)
      if (!manifest.meta.sampleBg) {
        const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor).catch((e) => { console.error(`  (bg sample skipped for ${route}: ${e.message})`); return null })
        const hex = rgbToHex(bg)
        if (hex) manifest.meta.sampleBg = hex // first non-transparent sample wins (for --theme=auto)
      }
      await page.screenshot({ path: png, fullPage: true })
      upsertScreen(manifest, { route, label: route, section: sectionOf(route), referencePng: `.work/captures/${id}.png`, structuralChecklist: undefined })
      captured.push(route)
      console.log(`  ✓ ${route} → ${id}.png`)
    } catch (e) { console.error(`  ✗ ${route}: ${e.message}`) }
  }
  writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2))
  await browser.close()
  console.log(`captured ${captured.length}/${targets.length}; manifest: ${MANIFEST}${manifest.meta.sampleBg ? ` (sampleBg ${manifest.meta.sampleBg})` : ''}`)
  if (!captured.length && targets.length) { console.error('captured 0 routes — check auth/connectivity'); process.exitCode = 1 }
}

export async function run(args) {
  const get = parseArgs(args)
  const cfg = readConfig(get)
  if (get('login')) return login(cfg)
  if (get('from-session')) return fromSession(cfg)
  return crawl(cfg, get)
}
