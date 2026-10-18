import { test } from 'node:test'
import assert from 'node:assert/strict'
import { routeToId, routeToPageName, emptyManifest, upsertScreen, setStatus } from './manifest.mjs'

test('routeToId slugs a route; home for /', () => {
  assert.equal(routeToId('/order/new'), 'order-new')
  assert.equal(routeToId('/'), 'home')
})

test('routeToPageName: no prefix by default, prefix when given (de-CG)', () => {
  assert.equal(routeToPageName('/orders'), 'orders')
  assert.equal(routeToPageName('/'), 'home')
  assert.equal(routeToPageName('/orders', 'Admin'), 'Admin · orders')
})

test('setStatus advances one step and rejects skips', () => {
  let m = upsertScreen(emptyManifest(), { route: '/orders', label: '/orders', section: 'orders', referencePng: 'x.png' })
  m = setStatus(m, 'orders', 'mapped')
  assert.equal(m.screens.orders.status, 'mapped')
  assert.throws(() => setStatus(m, 'orders', 'verified'), /illegal transition/)
})

test('upsertScreen preserves a prior checklist when omitted', () => {
  let m = upsertScreen(emptyManifest(), { route: '/o', label: '/o', section: 'o', referencePng: 'p', structuralChecklist: ['A'] })
  m = upsertScreen(m, { route: '/o', label: '/o', section: 'o', referencePng: 'p2' })
  assert.deepEqual(m.screens.o.structuralChecklist, ['A'])
})
