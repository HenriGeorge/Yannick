// site-cli.test.mjs — resolveSiteConfig: the shared --config parse + loadConfig + channel-resolve
// block folded out of site-palette/build/verify (#1215). Behavior-preserving extraction.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { writeFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { resolveSiteConfig } from './site-cli.mjs'

function cfgFile(obj) {
  const dir = mkdtempSync(join(tmpdir(), 'site-cli-'))
  const p = join(dir, 'site-to-figma.config.json')
  writeFileSync(p, JSON.stringify(obj))
  return p
}

test('resolveSiteConfig: parses --config, loads cfg, resolves channel from cfg', () => {
  const p = cfgFile({ origin: 'https://admin.example.com', channel: 'ch-from-cfg', canvasPage: '1:2' })
  const { cfg, CHANNEL, configPath, get } = resolveSiteConfig([`--config=${p}`], 'site-test', { requirePage: true })
  assert.equal(configPath, p)
  assert.equal(CHANNEL, 'ch-from-cfg')
  assert.equal(cfg.origin, 'https://admin.example.com')
  assert.equal(cfg.canvasPage, '1:2')
  assert.equal(typeof get, 'function')
})

test('resolveSiteConfig: FIGMA_CHANNEL env overrides cfg.channel', () => {
  const p = cfgFile({ origin: 'https://x.example.com', channel: 'ch-from-cfg', canvasPage: '1:2' })
  const prev = process.env.FIGMA_CHANNEL
  process.env.FIGMA_CHANNEL = 'ch-from-env'
  try {
    const { CHANNEL } = resolveSiteConfig([`--config=${p}`], 'site-test', {})
    assert.equal(CHANNEL, 'ch-from-env')
  } finally {
    if (prev === undefined) delete process.env.FIGMA_CHANNEL; else process.env.FIGMA_CHANNEL = prev
  }
})

test('resolveSiteConfig: returns a get() usable for other flags', () => {
  const p = cfgFile({ origin: 'https://x.example.com', channel: 'c' })
  const { get } = resolveSiteConfig([`--config=${p}`, '--theme=dark'], 'site-test', {})
  assert.equal(get('theme'), 'dark')
  assert.equal(get('missing'), undefined)
})

test('resolveSiteConfig: throws on a missing config file', () => {
  assert.throws(() => resolveSiteConfig(['--config=/no/such/site.json'], 'site-test', {}), /no config at/)
})

test('resolveSiteConfig: throws when no channel (cfg + env both absent)', () => {
  const p = cfgFile({ origin: 'https://x.example.com', canvasPage: '1:2' })
  const prev = process.env.FIGMA_CHANNEL
  delete process.env.FIGMA_CHANNEL
  try {
    assert.throws(() => resolveSiteConfig([`--config=${p}`], 'site-test', {}), /no channel/)
  } finally {
    if (prev !== undefined) process.env.FIGMA_CHANNEL = prev
  }
})

test('resolveSiteConfig: requirePage throws when canvasPage missing', () => {
  const p = cfgFile({ origin: 'https://x.example.com', channel: 'c' })
  assert.throws(() => resolveSiteConfig([`--config=${p}`], 'site-test', { requirePage: true }), /canvasPage/)
})
