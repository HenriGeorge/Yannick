import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve } from 'node:path'
import { ensureWorkIgnore } from './site-capture.mjs'

test('ensureWorkIgnore writes a .gitignore of "*" so .work/ auth never gets committed', () => {
  const work = mkdtempSync(resolve(tmpdir(), 'stf-work-'))
  try {
    ensureWorkIgnore(work)
    const gi = resolve(work, '.gitignore')
    assert.ok(existsSync(gi), '.work/.gitignore must exist')
    assert.equal(readFileSync(gi, 'utf8').trim(), '*')
  } finally { rmSync(work, { recursive: true, force: true }) }
})

test('ensureWorkIgnore does not clobber an existing .gitignore', () => {
  const work = mkdtempSync(resolve(tmpdir(), 'stf-work-'))
  try {
    writeFileSync(resolve(work, '.gitignore'), '*\n!keep.txt\n')
    ensureWorkIgnore(work)
    assert.match(readFileSync(resolve(work, '.gitignore'), 'utf8'), /!keep\.txt/)
  } finally { rmSync(work, { recursive: true, force: true }) }
})
