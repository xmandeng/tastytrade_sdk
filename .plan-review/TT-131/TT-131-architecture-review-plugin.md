# TT-131: `architecture-review` Plugin for claude-plugins Marketplace — Implementation Plan

> **Jira:** [TT-131](https://mandeng.atlassian.net/browse/TT-131)
> **Status:** Plan approved — all 10 sections green in plan-review round (2026-04-20)
> **Branch:** `feature/TT-131-architecture-review-plugin` (in `xmandeng/claude-plugins`)

## Context

The top-level `claude-plugins` README already advertises this as Coming Soon: *"interactive before/after component maps… same pattern: launched from the terminal, rendered in the browser, wired back into the live session."* This plan graduates that promise into a shipped plugin.

The plugin is named **`architecture-review`** (not `architecture`), invoked as `/architecture-review`. This mirrors `plan-review` / `/plan-review` so the sibling relationship is explicit in install command, slash command, output dir, env vars, and marketplace listing. "Review" reinforces that this is a structured-feedback checkpoint, not a one-shot diagram generator.

The internal `/architecture` skill in tastytrade_sdk (`.claude/skills/architecture/SKILL.md`) keeps its short name — only the published plugin takes the `-review` suffix.

## Workflow Fit

The marketplace README pitches a three-step observable agentic delivery workflow: **spec → architecture review → implementation**. `plan-review` owns *spec*. `architecture-review` owns *architecture review*. Same checkpoint pattern, same session handoff, different content surface (node graph instead of prose sections).

## Plugin Directory Layout

```
plugins/architecture-review/
├── .claude-plugin/plugin.json
├── assets/
│   ├── architecture-template.html    # forked from tastytrade template; terminal panel grafted in
│   ├── ARCHITECTURE_TEMPLATE.md      # authoring guide: node/edge schema, layer colors, layout rules
│   └── screenshots/                  # filled post-implementation for README
├── bin/
│   ├── devserver.py                  # copy of plan-review's + narrowly-scoped PUT handler
│   └── inject-session-id.sh          # identical to plan-review's (duplicate now, share later)
├── hooks/hooks.json                  # UserPromptSubmit → inject-session-id.sh
├── skills/architecture-review/SKILL.md
├── tests/
│   ├── conftest.py
│   └── test_devserver.py             # mirrors plan-review's WS framing + LAN IP tests, adds PUT tests
├── README.md
└── LICENSE                           # MIT
```

## Marketplace Registration

Append to `.claude-plugin/marketplace.json`:

```json
{
  "name": "architecture-review",
  "description": "Interactive before/after component diagrams for architecture reviews. Draggable node graph, saved layouts, and a Send-to-Claude button that drives a live Claude Code session via an embedded terminal.",
  "category": "productivity",
  "source": "./plugins/architecture-review",
  "homepage": "https://github.com/xmandeng/claude-plugins/tree/main/plugins/architecture-review"
}
```

## Skill Contract: `/architecture-review`

| Invocation | Behavior |
|---|---|
| `/architecture-review` | Infer ticket + title from conversation context; confirm before writing. |
| `/architecture-review <ticket>` | Accept any tracker format. Infer title from context; ask if unclear. |

### Output

- **Output dir:** `$ARCHITECTURE_REVIEW_DIR` → default `.architecture-review/`
- **Filename:** `<output-dir>/<ticket>-<slug>-architecture-review.html`
- **Layouts JSON:** `<output-dir>/<ticket>-<slug>-layouts.json` (written via PUT)
- **Default port:** 8775 (plan-review uses 8765 — both plugins can run side by side)

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ARCHITECTURE_REVIEW_DIR` | `.architecture-review/` | Output directory |
| `ARCHITECTURE_REVIEW_HOST` | auto-detected LAN IP | Override host in returned URL |
| `ARCHITECTURE_REVIEW_PORT` | `8775` | Devserver port |

## Prior-Run Detection & Resume

Lift plan-review's detection flow. Glob `"$OUT_DIR"/"$TICKET"-*-architecture-review.html`:

- Zero matches → write-new flow
- One match → offer Resume / Overwrite / Cancel
- Multiple → list with mtime, user picks

On Resume: hydrate `BEFORE_NODES` / `BEFORE_EDGES` / `AFTER_NODES` / `AFTER_EDGES` back into agent context, refresh only `CLAUDE_SESSION`, leave layouts JSON + localStorage intact.

## Template Port + Terminal Panel Graft

Fork `architecture-compare-template.html` into `plugins/architecture-review/assets/architecture-template.html` and apply:

1. **Graft terminal + handoff chrome** from `plan-review`'s `review-template.html`: xterm.js CDN scripts, `.terminal-panel` / `.handoff-bar` CSS, `CLAUDE_SESSION` constant, WS bridge, Hand-off-to-terminal button.
2. **Restructure layout** to dock a right-side terminal panel, collapsible via the same toggle plan-review uses. Feedback and terminal are mutually exclusive (same invariant as TT-127).
3. **Rename localStorage keys** to `arch-state:` + `PLAN_NAME`, `arch-layout:` + `PLAN_NAME`, `arch-autosave:` + `PLAN_NAME`.
4. **Keep `LAYOUTS_FILE`** feature with devserver PUT support (graceful localStorage + download fallback).
5. **Rewrite identifiers** at generation time: `<title>`, `<h1>`, `PLAN_NAME`, `CLAUDE_SESSION`, `LAYOUTS_FILE`.

## Send-to-Claude UX: Per-Node Comment Pins (Option C)

Click a node → the detail panel gains a **comment** textarea + a status pill (approve / revise / question). Comments persist in `localStorage`. **Send to Claude** button in the terminal panel aggregates all commented nodes into a structured bundle:

```
Here is my architecture-review of TT-131:

## Nodes flagged for revision (N)
### NodeLabel (pane, change)
File: path/to/file.py
Comment: ...

## Questions (N)
...

## Approved (N)
...
```

- Context-switch preamble (one-shot, same as plan-review)
- Feedback / terminal mutual exclusion
- Send button disabled until WS is OPEN and at least one node has non-pending status or a comment

## Devserver PUT Handler

Add `do_PUT` to `DevHandler`:

- Path allowlist: `*-layouts.json` under spawn cwd only; 403 otherwise
- Size cap: 256 KB; 413 otherwise
- Content-Type `application/json` required; 415 otherwise
- Validate JSON body; 400 on parse error
- Atomic write via `.tmp` + `os.rename`
- 204 No Content on success

## Testing Strategy

### Unit tests (`tests/test_devserver.py`)

Port plan-review's suite (WS framing, LAN IP resolution, DevHandler log filter) + PUT tests:
- happy path, non-layouts filename → 403, path traversal → 403, oversize → 413, non-JSON content-type → 415, invalid JSON → 400.

### Functional checklist (PR evidence)

1. `/plugin install architecture-review@xmandeng-plugins` succeeds
2. `/architecture-review TT-131` generates HTML + starts devserver + returns LAN URL
3. Before/after panes render, nodes draggable
4. Save named layout → persists to disk via PUT
5. Disable PUT → localStorage fallback + download works
6. Terminal bridge → `claude --resume <sid>` attaches
7. Per-node comment persists across reload
8. Send-to-Claude bundle streams into PTY
9. Handoff button releases browser child, copies resume command
10. Re-invoke `/architecture-review TT-131` → Resume restores nodes + comments

## Open Decisions (ratified)

- **D1. Share `bin/` across plugins?** No — duplicate now, revisit when a third plugin lands.
- **D2. Send-to-Claude UX:** Option C (per-node comment pins). Approved.
- **D3. Ticket split:** Single PR against TT-131. Pattern is known.
- **D4. Windows support:** Out of scope. Unix only (PTY).
- **D5. Port default:** 8775 (plan-review+10). Approved.

## Review Artifact

Approved plan-review HTML: `.plan-review/TT-131-architecture-plugin-for-claude-plugins-marketplace-review.html`
