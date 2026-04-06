---
name: architecture
description: Create an interactive before/after architecture diagram for solidifying implementation details after a plan is approved. Generates a draggable SVG-based comparison with component nodes, data flow edges, tooltips, code snippets, and change annotations. Usage - /architecture <TT-XXX> <title>
user-invocable: true
allowed-tools: Read, Write, Bash
---

# Architecture Diagram Skill

Creates an interactive before/after architecture comparison diagram from the architecture-compare template. Used after a plan is approved to solidify implementation details — component layouts, data flows, file paths, code snippets, and what changes.

## How It Works

1. Copies `docs/plans/features/architecture-compare-template.html` to `docs/plans/features/TT-XXX-<slug>-architecture.html`
2. Populates the `BEFORE_NODES`, `BEFORE_EDGES`, `AFTER_NODES`, `AFTER_EDGES` arrays with component data
3. Sets the page title, heading, autosave key, and layouts file
4. Starts the devserver serving `docs/plans/features/`
5. Returns the URL for the reviewer

## Usage

```
/architecture TT-105 MCP Migration
```

## Instructions

When this skill is invoked:

1. Parse arguments: first arg is the Jira ticket (e.g., `TT-105`), remaining args form the title
2. Construct the filename: `docs/plans/features/<ticket>-<slugified-title>-architecture.html`
3. Read `docs/plans/features/architecture-compare-template.html` as the base template
4. Ask the main agent to provide the architecture data (or build it from the approved plan). Each node needs:

### Node Properties

| Property | Required | Description |
|----------|----------|-------------|
| `id` | Yes | Unique identifier (used in edges) |
| `x`, `y` | Yes | Initial position on canvas (user can drag to rearrange) |
| `layer` | Yes | Color group: `orchestration`, `routing`, `queue`, or `signal` |
| `label` | Yes | Component name displayed on the node |
| `type` | Yes | Subtitle text (e.g., "Async Manager", "EventHandler") |
| `file` | No | Source file path (shown in detail panel) |
| `desc` | Yes | Tooltip description — what this component does |
| `code` | No | Code snippet shown in detail panel (use `\n` for newlines) |
| `badge` | No | Pill text below label (e.g., "7 channels") |
| `note` | No | Warning/callout text |
| `change` | No | **After pane only**: `new`, `modified`, or `removed` — highlights changes |

### Edge Properties

| Property | Required | Description |
|----------|----------|-------------|
| `from` | Yes | Source node id |
| `to` | Yes | Target node id |
| `label` | No | Edge label text |
| `style` | No | `new` (green, for After pane changes) or `callback` (dashed) |

5. Replace the four data arrays in the template:
   - `BEFORE_NODES` — components in the current architecture
   - `BEFORE_EDGES` — data flow connections in current architecture
   - `AFTER_NODES` — components after the change (with `change` annotations)
   - `AFTER_EDGES` — data flow connections after the change

6. Update identifiers:
   - `<title>` tag — `TICKET — TITLE: Before / After Architecture`
   - `<h1>` — `TICKET TITLE`
   - `AUTOSAVE_KEY` — `ticket-arch-compare-autosave` (lowercase)
   - `LAYOUTS_FILE` — `TICKET-architecture-compare-layouts.json`

7. Start the devserver if not running: `cd docs/plans/features && python3 docs/architecture-map/_devserver.py <port> &`
8. Return the URL: `http://localhost:<port>/<filename>.html`

## Features

The generated playground includes:

- **Split/Before/After views** — toggle between side-by-side comparison or individual panes
- **Draggable nodes** — reposition components to clarify layout (positions auto-saved)
- **Hover tooltips** — show component description
- **Click detail panel** — shows file path, code snippet, badge, notes
- **Change highlighting** — After pane nodes marked `new` (green), `modified` (amber), `removed` (red)
- **Edge animations** — optional flow animation toggle
- **Layout persistence** — positions saved to localStorage and optionally to a JSON file via PUT

## Workflow

This skill fits into the development workflow as:

1. `/plan-review TT-XXX Title` — high-level plan, section-by-section approval
2. `/architecture TT-XXX Title` — **solidify implementation details** with visual architecture
3. Implementation begins

## Node Layout Guidelines

Arrange nodes as a **top-down tree**, not a circular web. The user expects a clear directional flow:

1. **Source nodes at the top** — data origins (e.g., Brokerage WS, API) get the highest `y` values (smallest numbers)
2. **Processing nodes in the middle** — orchestrators, services that transform or route data
3. **Sink nodes at the bottom** — databases, message buses, terminal outputs get the largest `y` values
4. **Fan-out horizontally** — when a node writes to multiple sinks, spread them across the `x` axis on the same row
5. **Center the primary flow** — the main data path should run down the center; secondary paths branch left/right

**Typical spacing:** ~170px vertical gap between tiers, ~200px horizontal gap between siblings.

**Before pane example (3-tier):**
```
Source:     x:150, y:30   (centered)
Process:    x:100, y:200  (centered)
Sinks:      x:-90/130/360, y:420  (fanned out left-to-right)
```

**After pane with new intermediate tier:**
```
Source:     x:310, y:44
Process:    x:260, y:206
Middle:     x:466, y:372 / x:466, y:511  (new nodes between process and sinks)
Sinks:      x:-70/96/288, y:682  (fanned out, pushed down)
```

Avoid circular layouts where edges loop back up. Every edge should flow **downward** or **horizontally** — never upward except for explicit feedback/hydration paths.

## Layer Colors

| Layer | Color | Use For |
|-------|-------|---------|
| `orchestration` | Blue | Managers, coordinators, databases |
| `routing` | Default | Routers, handlers, middleware |
| `queue` | Purple | Processors, queues, buffers |
| `signal` | Green | Signals, events, sinks |

## Examples

See existing architecture diagrams for reference:
- `docs/plans/features/TT-85-architecture-compare.html` — Shared InfluxDB processor refactor
- `docs/plans/features/TT-64-architecture-compare.html` — Reconnect signal refactor
- `docs/plans/features/TT-60-architecture-compare.html` — Order events scoping
