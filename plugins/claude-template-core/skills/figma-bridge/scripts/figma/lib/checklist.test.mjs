import { test } from 'node:test'
import assert from 'node:assert/strict'
import { evaluate } from './checklist.mjs'

test('evaluate matches on the component: tag, else the full label (case-insensitive substring)', () => {
  const r = evaluate(['Orders table | component:Table', 'Pagination'], ['Table Default', 'Pagination'])
  assert.equal(r.ok, true)
  assert.deepEqual(r.items.map(i => i.present), [true, true])
})

test('evaluate reports a missing item', () => {
  const r = evaluate(['foo | component:Nope'], ['Table'])
  assert.equal(r.ok, false)
  assert.equal(r.items[0].present, false)
})
