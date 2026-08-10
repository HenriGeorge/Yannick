#!/usr/bin/env node
// PostToolUse(Write|Edit) hook (Node) — format the edited file with the project's
// local Prettier, if it applies. Silent no-op when Prettier isn't installed.
const { execSync } = require('node:child_process')

let raw = ''
process.stdin.on('data', (d) => (raw += d))
process.stdin.on('end', () => {
  let data = {}
  try {
    data = JSON.parse(raw || '{}')
  } catch {
    process.exit(0)
  }
  const fp = (data.tool_input || {}).file_path || ''
  if (!fp || !/\.(ts|tsx|js|jsx|cjs|mjs|css|scss|md|json)$/.test(fp)) process.exit(0)
  try {
    execSync(`npx --no-install prettier --write ${JSON.stringify(fp)}`, { stdio: 'ignore' })
  } catch {
    /* prettier not installed or file unformattable — don't block the edit */
  }
  process.exit(0)
})
