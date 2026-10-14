import { test } from 'node:test'
import assert from 'node:assert/strict'
import { parseConnect, buildCodeConnectIndex } from './code-connect-index.mjs'

const SRC = `import figma from '@figma/code-connect'
figma.connect(Button, 'https://figma.com/design/ABC123/DS?node-id=21153-566961', {})`

test('parseConnect lifts name from basename, node-id with ":" , fileKey', () => {
  const r = parseConnect(SRC, 'components/ui/Button.figma.tsx')
  assert.deepEqual(r, { name: 'Button', nodeId: '21153:566961', fileKey: 'ABC123' })
})

test('buildCodeConnectIndex skips unparseable files', () => {
  const idx = buildCodeConnectIndex([
    { path: 'Button.figma.tsx', content: SRC },
    { path: 'README.md', content: 'no connect here' },
  ])
  assert.deepEqual(Object.keys(idx), ['Button'])
})
