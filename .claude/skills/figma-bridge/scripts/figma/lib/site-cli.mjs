// site-cli.mjs — the shared CLI front-matter for the site-to-figma subcommands
// (site-palette / site-build / site-verify): parse `--config`, load + validate it, and resolve the
// talk-to-figma channel. Folded out of the three (they repeated this block verbatim — #1215).
//
// Lives HERE, not in site-config.mjs, on purpose: site-config.mjs is pure/zero-dep (no node:fs) so it
// can be unit-tested and reused without a filesystem; this helper does the fs read + env lookup.
import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { loadConfig } from './site-config.mjs'

/**
 * Resolve the config + channel for a site-to-figma subcommand.
 * @param {string[]} args the subcommand's argv (may carry `--config=<path>` and other `--k=v` flags)
 * @param {string} cmd the subcommand name, for error-message prefixes (e.g. "site-build")
 * @param {{requirePage?: boolean}} [opts] requirePage → loadConfig enforces `canvasPage` (palette/build)
 * @returns {{cfg: object, CHANNEL: string, configPath: string, get: (n: string) => string|undefined}}
 */
export function resolveSiteConfig(args, cmd, { requirePage = false } = {}) {
  const get = (n) => { const h = args.find((a) => a.startsWith(`--${n}=`)); return h ? h.slice(h.indexOf('=') + 1) : undefined }
  const configPath = get('config') ?? resolve(process.cwd(), 'site-to-figma.config.json')
  if (!existsSync(configPath)) throw new Error(`${cmd}: no config at ${configPath}`)
  const cfg = loadConfig(JSON.parse(readFileSync(configPath, 'utf8')), { requirePage })
  const CHANNEL = process.env.FIGMA_CHANNEL ?? cfg.channel
  if (!CHANNEL) throw new Error(`${cmd}: no channel (set \`channel\` in the config or FIGMA_CHANNEL)`)
  return { cfg, CHANNEL, configPath, get }
}
