import { test } from 'node:test'
import assert from 'node:assert/strict'
import { themeFor, luminance } from './theme.mjs'

test('luminance: black ~0, white ~1', () => {
  assert.ok(luminance('#000000') < 0.05)
  assert.ok(luminance('#ffffff') > 0.95)
})

test('themeFor auto picks dark for a dark sample, light for a light sample', () => {
  assert.equal(themeFor('auto', '#111111').cardBg, themeFor('dark').cardBg)
  assert.equal(themeFor('auto', '#fafafa').cardBg, themeFor('light').cardBg)
})

test('themeFor honors an explicit mode regardless of sample', () => {
  assert.equal(themeFor('light', '#000000').cardBg, themeFor('light').cardBg)
})

test('themeFor auto with no/unknown sample falls back to light (safe)', () => {
  assert.equal(themeFor('auto').cardBg, themeFor('light').cardBg)
  assert.equal(themeFor('auto', 'not-a-hex').cardBg, themeFor('light').cardBg)
})
