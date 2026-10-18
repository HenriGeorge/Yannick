---
name: meeting-minutes
description: 'Generate concise, actionable meeting minutes with metadata, decisions, action items (owner + due date), and follow-ups.'
---

# Meeting Minutes

## Purpose

Produce high-quality meeting minutes prioritizing decisions and action items. Output is designed to be clear, actionable, and easy to convert into GitHub Issues.

## Before Drafting — Ask Up to 3 Questions If Missing:

1. Meeting title, date, duration, and organizer?
2. Agenda or transcript/recording available?
3. Who should review the minutes?

## Output Structure

### 1. Metadata
- Title, Date (YYYY-MM-DD), Duration, Organizer, Location/Link

### 2. Attendance
- Present (names + roles), Absent, Notetaker

### 3. Summary
1-3 sentence overview of objective and outcome.

### 4. Decisions Made
- **Decision**: statement
  - Who decided, Rationale (1-2 sentences), Effective date

### 5. Action Items
- **[A1] Action**: description
  - **Owner**: Name
  - **Due**: YYYY-MM-DD
  - **Acceptance Criteria**: what completes this
  - **Linked**: issue/ticket URL (optional)

### 6. Notes by Agenda Item
Brief, factual notes per item. Open questions noted with owner.

### 7. Parking Lot
Unresolved items with next step and suggested owner.

### 8. Next Meeting
Proposed date/time and objectives.

## Style Rules

- Under 1 page for ≤30min meetings, under 2 pages for ≤60min
- Plain language, bullet lists
- Decisions and action items at the top
- Use ISO 8601 dates (YYYY-MM-DD)
- No speculation — uncertain items marked `TBD`
- Every action item MUST have owner and due date
