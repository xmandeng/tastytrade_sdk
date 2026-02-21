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

### Testing
- Unit tests required but NOT sufficient for PR approval
- Tests must pass
- Coverage target: 80%+ for new code

---

## Package Management

This project uses `uv` exclusively. Do NOT use `pip`.

- **Install all dependencies:** `uv sync`
- **Install production only:** `uv sync --no-dev`
- **Install base package only:** `uv pip install -e .`
- **Add a dependency:** `uv add <package>`
- **Add a dev dependency:** `uv add --group dev <package>`

**Why not pip?** Dev dependencies are declared under `[dependency-groups]` in `pyproject.toml` (PEP 735). `pip install -e ".[dev]"` will NOT work — pip does not support dependency groups. It also takes 4+ minutes vs under a second with `uv`.

**Never run:** `pip install`, `pip install -e .`, or `pip install -e ".[dev]"`

---

## Python Version

The required Python version is declared in `pyproject.toml` (`requires-python`). Do not hardcode version numbers elsewhere.

- `uv venv` and `uv sync` automatically resolve a compatible interpreter
- System Python may NOT meet requirements — always use `uv run` or activate the `.venv`
- Do not use bare `python` or `python3` — these may resolve to the system interpreter

---

## Worktree Setup

When working in git worktrees (e.g., `/tmp/worktrees/TT-XXX`):

1. Create the worktree: `git worktree add /tmp/worktrees/TT-XXX -b feature/TT-XXX-desc`
2. Set up the environment:
   ```bash
   cd /tmp/worktrees/TT-XXX
   uv venv
   uv sync
   ```
3. Verify: `uv run pytest --co -q`

Worktrees do NOT inherit the main repo's virtual environment. You must bootstrap every worktree.

---

## Development Commands

All commands use `uv run` to ensure the correct interpreter and dependencies:

- **Run tests:** `uv run pytest`
- **Type checking:** `uv run mypy src/`
- **Linting:** `uv run ruff check src/`

Bare commands (`pytest`, `mypy`, `ruff`) only work inside an activated `.venv`. Prefer `uv run` to avoid version mismatches.

---

## Reference Documents

- [docs/ISSUES_SPEC.md](docs/ISSUES_SPEC.md) - Jira issue specifications
- [docs/GITHUB_WORKFLOW_SPEC.md](docs/GITHUB_WORKFLOW_SPEC.md) - GitHub workflow standards
- [docs/PR_EVIDENCE_GUIDELINES.md](docs/PR_EVIDENCE_GUIDELINES.md) - PR evidence standards
- [docs/PR_EVIDENCE_CHECKLIST.md](docs/PR_EVIDENCE_CHECKLIST.md) - PR evidence checklist
