# TT-127: Living "Next Turn" Planning Portal — Scoping Document

> **Status:** SCOPING — second review pass. Decisions captured below; pending final approval before implementation.

> **Jira:** [TT-127](https://mandeng.atlassian.net/browse/TT-127)
> **Branch:** `feature/TT-127-planning-portal`

---

## Context

Today's planning workflow is multi-surface and manual:

1. Author `docs/plans/features/TT-XXX-<feature>.md` (the canonical plan)
2. Generate an HTML review playground (`-review.html`) — section-level Approve / Revise / Question marks plus freeform notes
3. Click "Copy Feedback as Prompt" — bundles marks into structured prompt text
4. **Paste the bundle into the running Claude Code session by hand**
5. Discuss, iterate, hand-edit the markdown
6. Regenerate the review playground, repeat

Step 4 is the friction. The bundle is structured exactly the way Claude needs it; the only thing missing is a wire from the playground into the running terminal session.

This plan removes step 4.

---

## Primary design constraint

**Enrich the existing review playground.** Do not replace it.

The current `docs/plans/review-template.html` workflow already does the hard work — section anchors, marks, notes, and the structured "Copy Feedback as Prompt" payload are all proven. The new portal is **the same template, with two additions**: an embedded terminal that hosts the user's Claude Code session, and a button on the feedback bundle that pipes the bundle directly into that terminal.

Anything that would require redesigning the existing template — new layouts, doc-toggle UI, per-section diff widgets, separate daemon processes — is out of scope. **The existing system is the system.** This supersedes any aesthetic ideas pulled from the Claude Design prototype.

---

## Goals

- **Eliminate the manual paste step** from the review loop.
- **Preserve full prior session context** by hosting the user's actual Claude Code session in-browser via `claude --continue`.
- **Stay inside the existing review template** — additions only, no architectural rewrite.
- **Keep all artifacts as-is on disk** — markdown plan + sibling `-review.html` files, exactly the layout we use today. No new folders, no new artifact types.

## Non-goals

- Multi-user collaboration.
- Auto-push to git. User runs `git add/commit` manually.
- Direct Anthropic API integration. The portal proxies to the user's local Claude Code session; it does not call the API.
- Materializing per-turn transcripts or diffs to disk. The Claude Code session and git history cover the audit trail.
- Persisting marks beyond what `localStorage` already handles in the existing template.
- Authentication. Loopback-only.
- Cloud hosting.

---

## Architecture

Two concrete additions to existing files. No new processes, no new package, no new daemon.

### 1. Extend `docs/architecture-map/_devserver.py`

Add a single websocket endpoint:

| Endpoint | Purpose |
|---|---|
| `WS /api/claude` | Spawns `claude --continue` in a PTY for the duration of the connection. Bidirectional bridge between the websocket and the PTY's stdin/stdout. |

Implementation: Python's `ptyprocess` (or stdlib `pty` + `select`). Per-connection isolation. When the websocket closes, the PTY is reaped.

Optional convenience endpoint (defer if not needed):

| Endpoint | Purpose |
|---|---|
| `GET /api/sessions` | Lists recent Claude Code sessions for the project (read from `~/.claude/projects/<hash>/sessions/`) so the playground can offer "resume specific session" instead of always `--continue`-ing the latest. |

### 2. Extend `docs/plans/review-template.html`

Two additions to the existing template:

- **Terminal panel** — collapsible panel that mounts xterm.js and connects to `WS /api/claude`. Sized as a sibling to the existing doc/feedback columns.
- **"Send to Claude" button** — appears next to the existing "Copy Feedback as Prompt" button. Generates the same bundle and writes it directly to the websocket's PTY stdin (terminated with `\n`). The bundle appears in the terminal as if the user had typed it.

Everything else in the template is unchanged. Marks, notes, navigation, prior approvals, rendering — all preserved.

### Component picture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser — review playground (existing template + 2 adds)   │
│                                                             │
│  ┌────────────┬─────────────┬─────────────────────────────┐ │
│  │  doc nav   │  doc body   │  ① xterm.js terminal       │ │
│  │            │  + marks    │     ↕ WS /api/claude        │ │
│  │            │             │                             │ │
│  │            │  [Send to   │  $ claude --continue        │ │
│  │            │   Claude]──►│  > <bundled feedback>       │ │
│  │            │      ②      │  (full session context)     │ │
│  └────────────┴─────────────┴─────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
        _devserver.py (extended) ↔ PTY ↔ `claude --continue`
```

### Out-of-band: doc edits

When discussion in the terminal converges on revisions, the Claude Code session in the PTY uses its **native `Edit` tool** to rewrite the source markdown directly. No separate `/api/write` endpoint, no special "Write" button in the UI. The `localStorage` marks state and the user's reload of the playground reflect the new doc content automatically.

---

## End-to-end target workflow

1. **Ideate** — create Jira ticket and feature branch (existing pattern, unchanged).
2. **Draft** — write `docs/plans/features/TT-XXX-<feature>.md` (existing flat layout, unchanged).
3. **Generate review** — invoke `/plan-review TT-XXX <title>` (existing skill, unchanged).
4. **Open in browser** — devserver is already running; open `http://<host>:8765/TT-XXX-<slug>-review.html`.
5. **Mark + note** — read the doc, mark sections (Approve / Revise / Question), drop inline notes. Identical to today.
6. **Send to Claude** — click the new button. The bundled feedback flows into the embedded terminal. The Claude Code session (`claude --continue`) discusses revisions with full prior context.
7. **Iterate** — converse in the terminal until alignment. The session may use Read/Edit/Bash tools natively to ground proposals and apply them.
8. **Edit applied** — Claude rewrites the source markdown via its `Edit` tool. Refresh the playground to see the revised doc with marks intact (per existing localStorage behavior).
9. **Wrap up** — when satisfied, exit the browser session. Optionally hop back to your original terminal Claude Code session and say "review the final result"; that session reads the now-revised `.md` from disk.
10. **Implement** — branch already exists; implementation proceeds against the finalized plan.

---

## Decisions table

| # | Decision | Resolution |
|---|---|---|
| Q1 | Migration path for existing flat plans | **Forward-only.** Existing plans stay where they are; the layout is unchanged anyway, so no migration is actually needed. |
| Q2 | Relationship to existing `/plan-review` skill | **Enrich, not replace.** The skill continues to generate review playgrounds; the playground template is what we extend. |
| Q3 | Architecture-compare integration | **Keep separate.** Architecture-compare remains a sibling artifact. |
| Q4 | Daemon language | **Python.** Extend the existing `_devserver.py` rather than introduce a new process. |
| Q5 | Versioning UI | **None.** No in-browser version toggle. The Claude Code session and git history are the audit trail. |
| Q6 | Claude model | **Whatever the user's Claude Code session is configured to use.** No model selection in the portal. |
| Q7 | CLI surface | **None.** Devserver is already running; user opens a URL. No new console_script needed. |
| Q8 | Persisting design bundle | **Deferred.** The bundle at `/tmp/design-fetch/tastydev/` is WIP reference; revisit once the enrichment design is finalized in implementation. |
| Q9 | v1 ship line | **Functional v1.** Websocket-PTY endpoint + xterm.js panel + "Send to Claude" button, demoed end-to-end on one real plan. |
| Q10 | Other constraints | Deferred items moved to TT-127 as "future considerations" (see below). |

---

## Acceptance criteria (v1 ship)

- `_devserver.py` exposes `WS /api/claude` that spawns `claude --continue` in a PTY and bridges stdin/stdout to the websocket
- `review-template.html` mounts an xterm.js panel that connects to `WS /api/claude` and renders the live Claude Code session
- The template's feedback section gains a "Send to Claude" button that writes the existing bundle payload to the websocket
- One real plan is reviewed end-to-end through the playground — bundled feedback sent, discussion held in-terminal, revisions applied via the embedded Claude session's `Edit` tool, source `.md` updated on disk, playground refreshed to show the revision

---

## Future considerations (not in v1, captured for the Jira)

- **Storage format for transcripts** — only relevant if we later decide to persist turn history. v1 explicitly does not.
- **Diff format** — same as above; defer.
- **Conflict handling** when the user hand-edits `plan.md` while the portal is open — likely needs a file-watch + reload prompt eventually; not a v1 blocker.
- **Multi-plan navigation** — jumping between TT-127 → TT-128 in one browser tab without restart. Nice-to-have, not v1.
- **Specific session resume** — `GET /api/sessions` listing if `--continue` (latest) ever proves insufficient.
- **Architecture-compare integration** — revisit if a real workflow need emerges.

---

## References

- **Existing review workflow** (the foundation we're extending):
  - `docs/plans/REVIEW_TEMPLATE.md` — the workflow guide
  - `docs/plans/review-template.html` — the template we extend
  - `docs/architecture-map/_devserver.py` — the server we extend
  - `docs/plans/features/TT-60-order-events-review.html` — canonical example of an existing review playground
- **Prototype design bundle** (Claude Design, 2026-04-17): `nextturn.html` + `BACKEND.md`. Currently at `/tmp/design-fetch/tastydev/`. Demoted to WIP reference per Q8; not the design target. The actual design target is the existing `review-template.html`.
- **Jira:** [TT-127](https://mandeng.atlassian.net/browse/TT-127)
