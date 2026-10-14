import { test } from 'node:test'
import assert from 'node:assert/strict'
import { extractRoutes } from './routes.mjs'

test('extractRoutes keeps same-origin pathnames, sorted & unique, drops cross-origin and non-http', () => {
  const origin = 'https://admin.example.com'
  const hrefs = [
    'https://admin.example.com/orders',
    'https://admin.example.com/orders',           // dup
    'https://admin.example.com/inventory',
    'https://other.example.com/x',                 // cross-origin
    'mailto:a@b.c',                                // non-http
    '/customers',                                  // relative → same origin
  ]
  assert.deepEqual(extractRoutes(hrefs, origin), ['/customers', '/inventory', '/orders'])
})

test('extractRoutes returns [] for no same-origin hrefs', () => {
  assert.deepEqual(extractRoutes(['https://x.com/a'], 'https://y.com'), [])
})
