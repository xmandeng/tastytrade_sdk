# CLAUDE.md

## Core Principles

1. **Evidence-Based Development** — demonstrate with real production data, not just tests
2. **Protocol-Based Design** — use protocols (abstract interfaces) over concrete implementations
3. **Type Safety** — strict type checking
4. **Immutability** — prefer immutable data structures where possible
5. **Observability** — instrument key operations

---

## CRITICAL: Mandatory Agent Usage — READ THIS FIRST

**STOP: Before starting ANY task, check which agent to use.**

This project enforces strict agent workflows. Direct Skill/Bash calls for Jira and GitHub operations are **intentionally blocked**.

**ALL Jira operations → `Task(subagent_type="jira-workflow", ...)`**
**ALL GitHub operations → `Task(subagent_type="github-workflow", ...)`**

### Recognition Patterns

- **"Work on TT-XXX"** → jira-workflow to get details, then github-workflow for implementation
- **"Create a PR"** → github-workflow agent
- **"Update Jira ticket"** → jira-workflow agent
- **"Create a Jira issue"** → jira-workflow agent
- **"Check PR status"** → github-workflow agent

### No Exceptions

Direct calls are **intentionally blocked**. If you get "Skill execution blocked by permission rules", you violated this requirement.

---

## Workflow Rules

### Jira Operations — MANDATORY DELEGATION

You MUST delegate ALL Jira operations to the jira-workflow agent. No exceptions.

**Operations:** create/update/search/comment on tickets, get details, link to Epics.

**Verbatim Content Rule:** When passing plans or implementation details to jira-workflow, include:
> "Use the following content VERBATIM. Do NOT paraphrase, summarize, or rewrite."

**Status transitions are automated** (branch → In Progress, PR → In Review, merge → Done). Do NOT manually transition.

**Epic governance:** Agent CAN create and link to Epics.

**Completion documentation:** When work is done, add implementation comment via jira-workflow with: Expected Behaviors (Before/After), Technical Implementation, Features, Verification Evidence.

**Quality assurance:** After every ticket update, jira-workflow MUST re-read and verify the ticket.

**Plan-ticket alignment:** Persist the full implementation plan to the ticket BEFORE starting work.

### GitHub Operations — MANDATORY DELEGATION

You MUST delegate ALL GitHub operations to the github-workflow agent. No exceptions.

**Autonomous PR creation:** When all ACs pass and code is pushed → create PR immediately. Do NOT ask permission.

**Operations:** create/list/view PRs, create/push branches, repository operations, PR reviews.

**Branch push requirement:** All new branches MUST be pushed to remote IMMEDIATELY after creation (triggers Jira automation).

### Pull Request Standards

**CRITICAL: Unit tests are NOT functional tests.** You MUST functionally test code before creating a PR.

- Run the code in a realistic environment and capture evidence
- Provide functional evidence for EACH acceptance criterion using real/production data
- If you cannot test: STOP, notify the user, do NOT create the PR

**PR quality assurance:** github-workflow agent MUST re-read and verify every PR after creation.

See [docs/PR_EVIDENCE_GUIDELINES.md](docs/PR_EVIDENCE_GUIDELINES.md) and [docs/PR_EVIDENCE_CHECKLIST.md](docs/PR_EVIDENCE_CHECKLIST.md) for evidence standards.

### Branch & Commit Rules

**No code changes without a Jira and branch** — ask if missing, reuse if available, only skip if explicitly told to. All edits MUST be made on the feature branch or worktree, never on `main`. Check out the branch BEFORE editing files.

**Branching:**
- NEVER work on `main` — github-workflow agent will REJECT operations
- ALWAYS create feature branch with Jira ticket: `feature/TT-XXX-description`
- MUST push immediately after creation: `git push -u origin <branch>`

**Commit format:** `TT-XXX: Brief description`
- Imperative mood ("Add" not "Added"), capitalize first word
- Jira ticket required in every commit
- No emojis, no generated signatures, no "Co-Authored-By: Claude"
- Examples: `TT-142: Refactor connection handling`, `TT-87: Fix message routing`

---

## Code Quality Standards

### Type Checking
- All code must pass type checking with zero errors
- Strict type hints on all functions

### Linting
- Must pass linting checks with zero errors
- No disabling rules without documented reason

### Naming
- Do NOT prefix private functions or methods with `_`. Use descriptive names without underscore prefixes.

### PII in Logging
- NEVER log account numbers, monetary balances, or other PII
- Log counts and status instead (e.g., "Fetched 3 positions" not "Fetched positions for account 5WT00001")
- Exception messages must not contain account numbers or lists of valid accounts

### Pydantic Model Config
- Inbound brokerage models MUST use `extra="allow"` — preserve all fields the brokerage sends
- Only outbound messages we construct (DXLink protocol, streamer connect/heartbeat) use `extra="forbid"`
- Never filter, reject, or discard fields from brokerage data without a documented design objective
- See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §1 for full design rule

### Concurrency
- Prefer event-driven design over timers and polling loops
- Avoid `while True` (infinite) loops — react to events instead (e.g., Redis pub/sub, asyncio.Event, queue.get)
- Ask if uncertain whether an event source exists before introducing a polling fallback

### Testing
- Unit tests required but NOT sufficient for PR approval
- Tests must pass
- Coverage target: 80%+ for new code

---

## Worktree Setup

When working in git worktrees (e.g., `/tmp/worktrees/TT-XXX`):

1. Create the worktree: `git worktree add /tmp/worktrees/TT-XXX -b feature/TT-XXX-desc`
2. Set up the environment:
   ```bash
   cd /tmp/worktrees/TT-XXX
   cp "$(git rev-parse --show-toplevel)/.env" .env
   uv venv
   uv sync
   ```
3. Verify: `uv run pytest --co -q`

Worktrees do NOT inherit the main repo's `.venv` or `.env`. You must bootstrap every worktree.

---

## Implementation Plans

Plans are saved to `docs/plans/` and **must** be associated with a Jira ticket if one exists. If no ticket exists, ask whether to create one.

**File naming:** `docs/plans/TT-XXX-<feature-name>.md`
- Always include the Jira ticket number as a prefix
- The plan title must reference the ticket: `# TT-XXX: Feature Name — Implementation Plan`
- Include a Jira link in the header: `> **Jira:** [TT-XXX](https://mandeng.atlassian.net/browse/TT-XXX)`

**Plan-ticket sync:** Persist the plan summary to the Jira ticket before starting implementation. The ticket should reference the plan file path and branch.

---

## Reference Documents

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - System architecture overview (start here)
- [CHANGELOG.md](CHANGELOG.md) - Sprint-by-sprint change history
- [docs/streaming_services.md](docs/streaming_services.md) - Streaming services operations guide
- [docs/signal_architecture.md](docs/signal_architecture.md) - Signal detection pipeline
- [docs/SERVICE_DISCOVERY.md](docs/SERVICE_DISCOVERY.md) - Configuration resolution
- [docs/ISSUES_SPEC.md](docs/ISSUES_SPEC.md) - Jira issue specifications
- [docs/GITHUB_WORKFLOW_SPEC.md](docs/GITHUB_WORKFLOW_SPEC.md) - GitHub workflow standards
- [docs/PR_EVIDENCE_GUIDELINES.md](docs/PR_EVIDENCE_GUIDELINES.md) - PR evidence standards
- [docs/PR_EVIDENCE_CHECKLIST.md](docs/PR_EVIDENCE_CHECKLIST.md) - PR evidence checklist
