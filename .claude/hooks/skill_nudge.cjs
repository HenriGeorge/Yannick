#!/usr/bin/env node
// PostToolUse skill-nudge — non-blocking notice when a Write/Edit touches a SKILL.md.
// Fires on a Write or Edit whose file_path matches `**/skills/*/SKILL.md` (any depth): emits a
// non-blocking `systemMessage` pointing at `superpowers:writing-skills` + the skill-quality
// checklist. Never blocks. Fail-open on any error.

const SKILL_MD_RE = /(^|[/\\])skills[/\\][^/\\]+[/\\]SKILL\.md$/

const NOTICE =
  "Notice: you're editing a SKILL.md directly. Skill authoring/edits should go through the " +
  'superpowers:writing-skills methodology (not ad-hoc edits) — see skill-creator\'s quality ' +
  'checklist before shipping this skill.'

async function main() {
  let raw = ''
  process.stdin.setEncoding('utf8')
  for await (const chunk of process.stdin) raw += chunk

  let data
  try {
    data = JSON.parse(raw || '{}')
  } catch {
    process.exit(0)
  }

  const toolName = data && data.tool_name
  if (toolName !== 'Write' && toolName !== 'Edit') process.exit(0)

  const filePath = data.tool_input && data.tool_input.file_path
  if (typeof filePath !== 'string' || !SKILL_MD_RE.test(filePath)) process.exit(0)

  process.stdout.write(JSON.stringify({ systemMessage: NOTICE }) + '\n')
  process.exit(0)
}

main().catch(() => {
  process.exit(0)
})
