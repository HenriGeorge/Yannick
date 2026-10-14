// site-config.mjs — load + validate a per-project site-to-figma.config.json. Pure, zero-dep.
const THEMES = new Set(['light', 'dark', 'auto'])

/**
 * @param {object} obj parsed site-to-figma.config.json
 * @param {{requirePage?: boolean}} [opts] requirePage: throw unless canvasPage is set (palette/build)
 * @returns {{origin,authDomain,channel,fileKey,canvasPage,pageNamePrefix,theme,uiDir,routesFile,screensSpec}}
 */
export function loadConfig(obj, { requirePage = false } = {}) {
  const o = obj ?? {}
  let url
  try { url = new URL(o.origin) } catch { throw new Error('site-config: `origin` is required and must be a full http(s) URL (e.g. https://admin.example.com)') }
  if (!/^https?:$/.test(url.protocol)) throw new Error('site-config: `origin` must be http(s)')
  const theme = o.theme ?? 'auto'
  if (!THEMES.has(theme)) throw new Error(`site-config: bad theme "${theme}" (want light|dark|auto)`)
  if (requirePage && !o.canvasPage) throw new Error('site-config: `canvasPage` is required for palette/build (a real Figma page id, not a PageDivider)')
  return {
    origin: url.origin,
    authDomain: o.authDomain ?? url.hostname,
    channel: o.channel,
    fileKey: o.fileKey,
    canvasPage: o.canvasPage,
    pageNamePrefix: o.pageNamePrefix ?? '',
    theme,
    uiDir: o.uiDir ?? 'components/ui',
    routesFile: o.routesFile,
    screensSpec: o.screensSpec,
  }
}
