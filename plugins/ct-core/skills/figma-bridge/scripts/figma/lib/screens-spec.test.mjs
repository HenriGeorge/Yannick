import { test } from 'node:test'
import assert from 'node:assert/strict'
import { navItem, col, row, rect, txt, comp, collectComponents, loadScreens } from './screens-spec.mjs'

test('navItem is a horizontal row of an icon-placeholder rect + a label text', () => {
  const n = navItem('Orders')
  assert.equal(n.layout.dir, 'HORIZONTAL')
  assert.equal(n.children.length, 2)
  assert.equal(n.children[0].rect, true)          // icon placeholder
  assert.equal(n.children[1].text, 'Orders')       // label
})

test('collectComponents returns unique component names in a tree', () => {
  const tree = col('root', [comp('Table'), row('r', [comp('Button'), comp('Table')])])
  assert.deepEqual(collectComponents(tree).sort(), ['Button', 'Table'])
})

test('loadScreens rejects a node that is neither leaf nor a layout frame', () => {
  assert.throws(() => loadScreens({ s: { route: '/s', name: 's', tree: { name: 'x' } } }), /invalid node/)
})

test('loadScreens accepts a valid screen tree', () => {
  const screens = { s: { route: '/s', name: 's', tree: col('s', [txt('hi'), rect('box')]) } }
  assert.equal(loadScreens(screens), screens)
})
