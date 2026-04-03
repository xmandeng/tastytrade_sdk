---
name: plan-review
description: Create an interactive HTML review playground for an implementation plan. Generates a section-by-section reviewable document with approve/revise/question controls and a "Copy Feedback as Prompt" button. Usage - /plan-review <TT-XXX> <title>
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Plan Review Skill

Creates an interactive HTML review playground from the review template, pre-populated with plan sections. The reviewer can approve, flag for revision, or ask questions on each section, then copy structured feedback as a prompt.

## How It Works

1. Copies `docs/plans/review-template.html` to `docs/plans/TT-XXX-<slug>-review.html`
2. Populates the `docSections` array with plan content provided by the main agent
3. Sets the page title, heading, and `PLAN_NAME` constant
4. Starts the devserver on port 8765 serving `docs/plans/`
5. Returns the URL for the reviewer

## Usage

```
/plan-review TT-105 MCP Migration
```

## Instructions

When this skill is invoked:

1. Parse arguments: first arg is the Jira ticket (e.g., `TT-105`), remaining args form the title (e.g., `MCP Migration`)
2. Construct the filename: `docs/plans/<ticket>-<slugified-title>-review.html` (lowercase, hyphens)
3. Read `docs/plans/review-template.html` as the base template
4. Ask the main agent to provide the plan sections. Each section needs:
   - `id` — unique slug for DOM IDs and navigation
   - `title` — displayed in nav and section header
   - `content` — markdown-like content (supports `**bold**`, `` `code` ``, fenced code blocks, `### Heading`, `- list items`, `| tables |`, `[links](url)`)
   - `revised` (optional) — set to `true` to highlight as updated in subsequent review rounds
5. Replace the `docSections` array in the template with the provided sections
6. Update three identifiers:
   - `<title>` tag — `Plan Review: <ticket>: <title>`
   - Topbar `<h1>` — `<ticket>: <title>`
   - `PLAN_NAME` constant — `<ticket>: <title>`
7. Write the file to `docs/plans/`
8. Start the devserver if not already running: check `lsof -i :8765`, if not running start with `cd docs/plans && python3 docs/architecture-map/_devserver.py 8765 &`
9. Return the URL: `http://localhost:8765/<filename>.html`

## Structuring Good Review Sections

Each section should be **independently reviewable** — one decision or approval point per section. Guidelines from `docs/plans/REVIEW_TEMPLATE.md`:

- **One concern per section** — avoid mixing unrelated topics
- **Actionable titles** — the reviewer should know what they're approving from the nav alone
- **Context first** — lead with a Context section that frames the problem
- **Decision sections last** — put scoping checklists and open questions at the end

## Handling Review Feedback

When the reviewer pastes feedback from the "Copy Feedback as Prompt" button:

1. Parse the approved/revision/question sections
2. For revisions: update the `content` of affected sections and set `revised: true`
3. For prior approvals: add to the `priorApprovals` object so they show as pre-approved on reload
4. Rewrite the HTML file with updates
5. Tell the reviewer to refresh

## Content Format Reference

The `content` field supports markdown-like syntax rendered by the built-in `renderMarkdown()`:

| Syntax | Renders as |
|--------|-----------|
| `**bold**` | bold |
| `` `inline code` `` | inline code |
| ` ```code block``` ` | fenced code block |
| `### Heading` | h4 subheading |
| `- item` or `* item` | unordered list |
| `1. item` | ordered list |
| `\| col \| col \|` | table (first row = header, skip separator row) |
| `[text](url)` | clickable link (opens in new tab) |

Use template literal backtick strings for content to allow multi-line text. Escape backticks within content with `\` + backtick.
