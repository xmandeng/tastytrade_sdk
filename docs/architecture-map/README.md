# Architecture Concept Map

Interactive visual explorer for the TastyTrade SDK data pipeline — from DXLink WebSocket through queues, processors, and into InfluxDB/Redis.

## Quick Start

```bash
cd docs/architecture-map
python3 _devserver.py
```

Then open **http://localhost:8765/architecture_playground.html** in your browser.

If using VS Code Remote SSH, the port will auto-forward — check the **Ports** tab.

## What's In Here

| File | Purpose |
|------|---------|
| `architecture_playground.html` | The interactive concept map (self-contained, no build step) |
| `architecture_layouts.json` | Saved node layouts (commit these to share with the team) |
| `_devserver.py` | Tiny HTTP server with PUT support for persisting layouts |

## How To Use

### Navigation

| Action | Effect |
|--------|--------|
| **Click** a node | Open detail panel (description, insights, code, connections) |
| **Scroll wheel** | Zoom in/out |
| **Drag** canvas | Pan |
| **Drag** a node | Reposition it |
| **F** | Fit all nodes to screen |
| **R** | Reset pan/zoom |
| **Space** | Toggle data flow animation |

### Group Selection

| Action | Effect |
|--------|--------|
| **Shift+Click** nodes | Add/remove from group |
| **Shift+Drag** canvas | Lasso select multiple nodes |
| **Cmd/Ctrl+A** | Select all visible nodes |
| **Cmd/Ctrl+C** | Copy selected node(s) metadata as JSON |
| Drag any grouped node | Moves the entire group |
| **Escape** or click canvas | Clear group |

### Layout Management

| Action | Effect |
|--------|--------|
| **Ctrl+Z** / **Ctrl+Shift+Z** | Undo / redo node moves |
| **Reset** button | Snap all nodes to default positions |
| **Save** button | Save current layout (persists to `architecture_layouts.json`) |
| **Load** dropdown | Restore a saved layout |

### Layer Toggles

The top bar has colored pills for each architectural layer. Click to show/hide:

- **WebSocket** — DXLink connection, listener, keepalive
- **Queues** — Per-channel asyncio queues
- **Routing** — MessageRouter, EventHandler, BaseEvent models
- **Processors** — InfluxDB writer, Redis publisher, signal processor, etc.
- **Persistence** — InfluxDB, Redis
- **Signal** — Decoupled signal service, HullMacdEngine
- **Config** — SubscriptionStore, CHANNEL_SPECS

## Insights

Nodes with a **cyan dot** in the top-right corner have attached insights — design rationale and implementation notes from the author (**Mandeng**, orange) and code analysis (**Claude**, purple). These appear in the detail panel when you click the node.

## Keeping It Current

This map is a living document. When the architecture changes:

1. Edit the `nodes` and `edges` arrays in `architecture_playground.html`
2. Add `insights` to capture the "why" behind changes
3. Save a new layout if the topology shifted
4. Commit `architecture_playground.html` and `architecture_layouts.json`
