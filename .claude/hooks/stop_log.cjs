#!/usr/bin/env node
// Stop hook (Node) — append a session-end marker to .claude/session-logs/.
const fs = require('node:fs')
const path = require('node:path')

const dir = process.env.CLAUDE_PROJECT_DIR || process.cwd()
const logDir = path.join(dir, '.claude', 'session-logs')
try {
  fs.mkdirSync(logDir, { recursive: true })
  fs.appendFileSync(path.join(logDir, 'sessions.log'), `${new Date().toISOString()} session ended\n`)
} catch {
  /* best-effort logging */
}
process.exit(0)
