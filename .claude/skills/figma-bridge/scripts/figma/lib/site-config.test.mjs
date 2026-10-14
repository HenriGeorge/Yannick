import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loadConfig } from './site-config.mjs'

test('loadConfig requires a valid origin', () => {
  assert.throws(() => loadConfig({}), /origin/)
  assert.throws(() => loadConfig({ origin: 'not-a-url' }), /origin/)
})

test('loadConfig defaults authDomain from origin host, prefix empty, theme auto', () => {
  const c = loadConfig({ origin: 'https://admin.example.com' })
  assert.equal(c.authDomain, 'admin.example.com')
  assert.equal(c.pageNamePrefix, '')
  assert.equal(c.theme, 'auto')
})

test('loadConfig rejects an unknown theme and requires canvasPage when asked', () => {
  assert.throws(() => loadConfig({ origin: 'https://x.io', theme: 'neon' }), /theme/)
  assert.throws(() => loadConfig({ origin: 'https://x.io' }, { requirePage: true }), /canvasPage/)
})
