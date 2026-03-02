# Plan Review Playground — Template Guide

Self-contained HTML playgrounds for reviewing implementation plans. Designed for iPad + desktop use with touch-friendly controls.

## Quick Start

1. Copy `review-template.html` to `TT-XXX-<feature>-review.html`
2. Update the `<title>` and topbar `<h1>`
3. Replace the `docSections` array with your plan sections
4. Update the plan name in `generatePrompt()`
5. Serve with `/devserver <port> docs/plans`

## Customizing Content

All content lives in the `docSections` array at the top of the `<script>` block. Each section is an object:

```javascript
{
  id: "unique-slug",          // Used for DOM IDs and navigation
  title: "Section Title",     // Displayed in nav and section header
  revised: false,             // Optional — highlights section as revised (blue) until reviewed
  content: `Markdown-like content here...`
}
```

### Content Format

The `content` field supports a markdown-like syntax rendered by the built-in `renderMarkdown()` function:

| Syntax | Renders as |
|--------|-----------|
| `**bold**` | **bold** |
| `` `inline code` `` | inline code |
| ` ```code block``` ` | fenced code block |
| `### Heading` | h4 subheading |
| `- item` or `* item` | unordered list |
| `1. item` | ordered list |
| `\| col \| col \|` | table (first row = header, skip separator row) |

### Pre-Approved Sections

To mark sections as already approved (e.g., from a prior review round), add a `priorApprovals` object and apply statuses in the state initialization:

```javascript
const priorApprovals = {
  "section-id": "approved",
  "other-section": "approved"
};

// In state init:
const state = {
  sections: docSections.map(s => ({
    ...s,
    status: priorApprovals[s.id] || 'pending',
    comment: ''
  })),
  ...
};
```

## Layout

Three-panel layout: **Nav** (240px) | **Document** (flex) | **Feedback** (360px)

- Panels are resizable via drag handles between them
- Panels are fully collapsible via topbar toggle buttons (sidebar icons)
- Touch-friendly: `touchend` handlers + `@media (hover: hover)` for desktop-only hover states
- Collapse toggles use a smooth 0.3s transition with synchronized `background`, `border-color`, and `color`

## Review Workflow

1. Read each section in the document panel
2. Click **Approve**, **Needs Revision**, or **Question** per section
3. Add comments (auto-shown for revision/question, manual via Comment button)
4. Review summary appears in the right feedback panel with filter tabs
5. Click **Copy Feedback as Prompt** to get a formatted markdown prompt for Claude

## Key Behaviors

- **Status toggling**: Clicking an active status button resets to pending
- **Revised sections**: Blue highlight only shows while status is pending; review status color takes over once set
- **Comment persistence**: Comments saved on textarea blur; existing comments show with an edit button
- **Feedback filters**: All / Approved / Needs Revision / Questions tabs in right panel

## Files

- `review-template.html` — Blank template, ready to fill with content
- `TT-62-strategy-engine-review.html` — Example: strategy classification engine review
- `TT-63-design-review.html` — Example: futures option entry price reconciliation review
