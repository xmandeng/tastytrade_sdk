# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Principles

1. **Evidence-Based Development**: Features must be demonstrated with real production data, not just test results
2. **Protocol-Based Design**: Use protocols (abstract interfaces) over concrete implementations
3. **Type Safety**: Maintain strict type checking with MyPy/Pyright
4. **Immutability**: Use frozen Pydantic models where possible
5. **Observability**: Add instrumentation for key operations

---

## ⚠️ CRITICAL: Mandatory Agent Usage - READ THIS FIRST

**STOP: Before starting ANY task, check which agent to use.**

This project enforces strict agent workflows. Direct Skill/Bash calls for Jira and GitHub operations are **intentionally blocked**.

### Quick Reference

**ALL Jira operations → jira-workflow agent**
**ALL GitHub operations → github-workflow agent**

### Recognition Patterns

**Start your workflow correctly:**

1. **User says: "Work on TT-XXX"**
   - First action: Use `Task(subagent_type="jira-workflow", ...)` to get issue details
   - After understanding the task: Use appropriate agent (often github-workflow for implementation)

2. **User says: "Create a PR"**
   - Use `Task(subagent_type="github-workflow", ...)`

3. **User says: "Update Jira ticket status"**
   - Use `Task(subagent_type="jira-workflow", ...)`

### No Exceptions

Direct calls are **intentionally blocked** to enforce proper workflow. If you get "Skill execution blocked by permission rules", you violated this requirement.

---

## Development Environment

This project uses UV for fast dependency management and is designed to run in a development container with pre-configured services. The Dockerfile includes UV, Node.js, and Claude Code pre-installed for optimal performance.

## Common Commands

### Environment Setup
- `uv sync --dev` - Install all dependencies including dev dependencies
- `uv sync` - Install only production dependencies
- `docker-compose up -d` - Start infrastructure services (InfluxDB, Redis, Telegraf, Grafana)
- `cp .env.example .env` - Copy environment template (edit with credentials)

### Code Quality
- `uv run ruff check .` - Lint code with Ruff
- `uv run ruff format .` - Format code with Ruff (replaces Black/isort)
- `uv run mypy .` - Type checking with MyPy

### Testing
- `uv run pytest` - Run all tests
- `uv run pytest unit_tests/` - Run specific test directory
- `uv run pytest -v` - Run tests with verbose output
- `uv run pytest --cov` - Run tests with coverage

### Application
- `uv run api` - Start the FastAPI server
- `uv run tasty-subscription` - Market data subscription CLI (see below)
- Script entry points available in `src/tastytrade/scripts/`

### Market Data Subscription CLI (`tasty-subscription`)

The `tasty-subscription` CLI manages market data subscriptions including historical backfill, live streaming, and operational monitoring.

**Commands:**

```bash
# Start subscription with historical backfill and live streaming
uv run tasty-subscription run \
  --start-date 2026-01-15 \
  --symbols AAPL,SPY,QQQ \
  --intervals 1d,1h,5m \
  --log-level INFO

# Query status of active subscriptions
uv run tasty-subscription status
uv run tasty-subscription status --json
```

**Run Command Options:**
| Option | Required | Description |
|--------|----------|-------------|
| `--start-date` | Yes | Historical backfill start date (YYYY-MM-DD) |
| `--symbols` | Yes | Comma-separated symbols (e.g., `AAPL,SPY,QQQ`) |
| `--intervals` | Yes | Comma-separated intervals: `1d`, `1h`, `30m`, `15m`, `5m`, `m` |
| `--log-level` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`) |
| `--health-interval` | No | Seconds between health logs (default: `300`) |

**Full Production Example:**
```bash
uv run tasty-subscription run \
  --start-date 2026-01-20 \
  --symbols BTC/USD:CXTALP,NVDA,AAPL,QQQ,SPY,SPX \
  --intervals 1d,1h,30m,15m,5m,m \
  --log-level INFO
```

**Expected Output:**
```
TastyTrade Market Data Subscription - Starting
Configuration:
  Start Date:  2026-01-20
  Symbols:     BTC/USD:CXTALP, NVDA, AAPL, QQQ, SPY, SPX
  Intervals:   1d, 1h, 30m, 15m, 5m, m
  Feed Count:  36 candle feeds
Subscribing to ticker feeds for 6 symbols
Subscribing to 36 candle feeds from 2026-01-20
Subscription and back-fill complete for 36/36 subscriptions
Subscription active - press Ctrl+C to stop
Health — Uptime: 5m | 6 channels active
```

**Graceful Shutdown:** Press `Ctrl+C` for clean shutdown (flushes data, closes connections).

## Architecture Overview

This is a high-performance Python SDK for TastyTrade's Open API with real-time market data processing capabilities.

### Core Components

**Data Flow Pipeline:**
1. **DXLinkManager** (`src/tastytrade/connections/sockets.py`) - WebSocket connection management and real-time market data streaming
2. **MessageRouter** (`src/tastytrade/messaging/`) - Event parsing, routing, and processing with multiple processors (Telegraf, Redis, Default)
3. **Data Storage** - InfluxDB for time-series data, Redis for pub/sub distribution
4. **Analytics Engine** (`src/tastytrade/analytics/`) - Technical indicators, visualizations, and interactive charts

**Key Modules:**
- `src/tastytrade/connections/` - API connections, WebSocket management, subscriptions
- `src/tastytrade/messaging/` - Event models, message processing, and routing
- `src/tastytrade/providers/` - Market data providers and subscription management
- `src/tastytrade/analytics/` - Technical indicators, charting, and visualizations
- `src/tastytrade/dashboard/` - Interactive dashboards using Dash/Plotly
- `src/tastytrade/config/` - Configuration management and enumerations

### Infrastructure Services

Required services (managed via docker-compose):
- **InfluxDB** (port 8086) - Time-series database for market data storage
- **Redis** (port 6379) - Message queue and caching
- **Telegraf** (port 8186) - Data collection and routing
- **Grafana** (port 3000) - Monitoring and visualization dashboards
- **Redis-Commander** (port 8081) - Redis management interface

---

## Jira Operations Protocol - MANDATORY DELEGATION

**CRITICAL:** You MUST delegate ALL Jira operations to the jira-workflow agent. This is not optional.

### Why This Matters

The jira-workflow agent is the **mandatory gatekeeper** for all Jira operations. It enforces:
- **Intelligent type selection** (Story/Task/Bug/Sub-task based on request analysis)
- **Quality standards** (Test Evidence Requirements embedded in all templates)
- **Epic governance** (can link to Epics, cannot create Epics)
- **Validation rules** (ensures tickets meet project standards)
- **Type-agnostic workflow** (dispatcher processes any ticket type)

### What Operations Require Delegation

**ALWAYS use jira-workflow agent for:**
- Creating tickets (Story, Task, Bug, Sub-task - NOT Epic)
- Updating tickets (fields, descriptions, priorities)
- Linking tickets (to Epics, to parent issues)
- Searching tickets (JQL queries)
- Adding comments to tickets
- Getting ticket details
- Managing sprints (when applicable)

**When to use:**
- User mentions a Jira ticket (TT-XXX)
- User asks to "work on TT-XXX" or "start TT-XXX"
- Need to get issue details, update status, add comments
- Need to create new issues or search existing ones

**NEVER use Jira operations directly.** Always delegate to jira-workflow agent via the Task tool.

### Correct Usage Pattern

✅ **Correct - Delegate to jira-workflow agent:**
```python
# When you need to create a Jira ticket
Task(
    subagent_type="jira-workflow",
    description="Create Jira ticket for feature",
    prompt="""
    Create a ticket for the following work:

    Feature: Add WebSocket reconnection logic
    Context: Users need automatic reconnection when market data streams disconnect
    Priority: High

    Please create the appropriate ticket type (Story/Task/Bug) based on this request
    and link it to the relevant Epic if obvious from context.
    """
)
```

✅ **Correct - Let agent determine type:**
```python
# Agent will analyze "fix bug" and create Bug ticket
Task(
    subagent_type="jira-workflow",
    description="Create ticket for bug fix",
    prompt="Create ticket: Fix message routing failure on malformed events"
)
```

✅ **Correct - Searching tickets:**
```python
Task(
    subagent_type="jira-workflow",
    description="Find tickets in epic",
    prompt="Find all Stories in Market Data epic (TT-1) that are in To Do status"
)
```

### Incorrect Usage (DO NOT DO THIS)

❌ **Incorrect - Using Jira operations directly:**
```python
# NEVER DO THIS - These are BLOCKED:
Skill(command="jira-operations")  # Will fail with permission error
Bash("jira-cli ...")              # Blocked
bash .claude/skills/jira-operations/scripts/create-issue.sh "..." "..." "Story"
```

❌ **Incorrect - Trying to create Epics:**
```python
# NEVER DO THIS - Epics are team-managed strategic tools
Task(
    subagent_type="jira-workflow",
    prompt="Create Epic for Q2 Roadmap"
)
# jira-workflow agent will correctly decline this request
```

### Type-Agnostic Approach

The jira-workflow agent uses **intelligent type selection**:
- Analyzes your request and keywords
- Automatically selects Story/Task/Bug/Sub-task
- Asks for clarification if ambiguous
- Refuses to create Epics (team governance)

**You don't need to specify the type** - just describe what needs to be done, and the agent will select appropriately:

```python
# These requests automatically get correct type
"Add real-time quote streaming" → Story (user-facing feature)
"Refactor message router logic" → Task (technical work)
"Fix WebSocket connection drops" → Bug (defect)
"Create API endpoint under TT-50" → Sub-task (implementation piece)
```

### Status Transitions

**Important:** Status transitions are handled by GitHub workflows, NOT by you or jira-workflow agent:
- Branch created → Jira moves to "In Progress" (via `.github/workflows/jira-transition.yml`)
- PR opened → Jira moves to "In Review" (automated)
- PR merged → Jira moves to "Done" (automated)

jira-workflow agent has read-only status awareness. Do not manually transition tickets.

### Epic Governance

**CRITICAL:** Epics are strategic planning tools managed by the team.

- ✅ Agent CAN link tickets to existing Epics
- ❌ Agent CANNOT create new Epics

If you need an Epic created, ask the team to create it manually in Jira, then use jira-workflow agent to link tickets to it.

### Implementation Completion Documentation (MANDATORY)

**When you complete work on a Jira ticket, you MUST add a comprehensive implementation comment.**

The comment MUST include:

1. **Expected Behaviors** (MOST IMPORTANT)
   - Describe changes from user/operational perspective
   - Use Before/After format for each behavioral change
   - Be specific: "Status now shows '8s ago' for active feeds" not "improved status display"

2. **Technical Implementation**
   - New components added (classes, functions, enums)
   - Modified components with explanations
   - Data flow changes if architectural

3. **Features Added/Removed**
   - Tables listing all features with file locations
   - Reasons for any removed features

4. **Verification Evidence**
   - Test results (unit, integration, live)
   - Specific examples with real data

**Example Expected Behaviors section:**
```
Before: Status showed subscription creation time, not actual data flow
After: Status shows when data was last received (e.g., "8s ago" updating in real-time)

Before: Constant "stale: Profile, Summary" warnings even when feeds were healthy
After: No false staleness warnings - low-frequency feeds are expected behavior
```

The jira-workflow agent has detailed templates for this. Always delegate completion comments to it.

### Jira Quality Assurance (MANDATORY)

After creating or updating any Jira ticket, the jira-workflow agent MUST:

1. **Re-read the ticket** to verify it was created correctly
2. **Check completeness** against quality standards
3. **Fix any deficiencies** before reporting back
4. **Report confidence level** to you (✅ complete or ⚠️ needs attention)

This ensures tickets are properly documented and nothing is missed.

### Plan-Ticket Alignment (MANDATORY)

When planning work for a Jira ticket, you MUST ensure the ticket description includes the full implementation plan:

1. **Before implementation begins**, update the Jira ticket with:
   - Detailed implementation steps with file paths and line numbers
   - Code snippets showing current vs proposed changes
   - Design rationale (why this approach)
   - Updated acceptance criteria matching the plan

2. **Why this matters:**
   - Other agents may pick up the work without context from the planning session
   - The Jira ticket is the source of truth for what should be implemented
   - Plans discussed in conversation are lost if not persisted to Jira

3. **Verification:**
   - After updating, re-read the ticket to confirm all plan details are present
   - Ensure acceptance criteria match implementation plan exactly

---

## GitHub Operations Protocol - MANDATORY DELEGATION

**CRITICAL:** You MUST delegate ALL GitHub operations to the github-workflow agent. This is not optional.

### 🤖 Autonomous PR Creation (MANDATORY)

**When all ACs pass and code is pushed → Create PR immediately. Do NOT ask permission.**

```
Branch created → Jira: In Progress
Code pushed + ACs pass → Create PR → Jira: In Review
PR merged (human) → Jira: Done
```

### Why This Matters

The github-workflow agent is the **mandatory gatekeeper** for all GitHub operations. It enforces:
- **PR title format** (TT-XXX: Description)
- **PR body structure** (Summary, Related Jira Issue, Acceptance Criteria, Evidence, Test Evidence, Changes Made)
- **Branch naming conventions** (type/TT-XXX-description)
- **Commit message format** (TT-XXX: Description)
- **Functional evidence requirements** (mandatory for each AC)
- **Quality gates** (tests, type checking, linting)
- **CRITICAL: Immediate branch push** after creation to trigger Jira automation

### What Operations Require Delegation

**ALWAYS use github-workflow agent for:**
- Creating pull requests
- Getting PR status and details
- Listing pull requests
- Viewing PR file changes
- Creating and pushing branches (CRITICAL: must push immediately after creation)
- Repository operations (commits, git operations)

**When to use:**
- Creating, listing, or viewing pull requests
- Any gh CLI operations
- Modifying files in `.claude/skills/github-operations/`
- Repository operations (branches, commits, tags)
- PR reviews, comments, status checks

**NEVER use GitHub operations directly.** Always delegate to github-workflow agent via the Task tool.

### Correct Usage Pattern

✅ **Correct - Delegate to github-workflow agent:**
```python
# When you need to create a PR
Task(
    subagent_type="github-workflow",
    description="Create PR for feature",
    prompt="""
    Create a pull request for the completed work:

    Branch: feature/TT-XXX-description
    Base: main
    Title: TT-XXX: Brief description

    Summary: [what was done]
    Changes: [list of changes]
    Evidence: [functional evidence for each AC from Jira ticket]
    """
)
```

✅ **Correct - Creating and pushing a branch:**
```python
# Agent will create branch and IMMEDIATELY push to trigger Jira automation
Task(
    subagent_type="github-workflow",
    description="Create and push feature branch",
    prompt="Create branch feature/TT-XXX-add-feature and push immediately to remote"
)
```

✅ **Correct - Getting PR status:**
```python
Task(
    subagent_type="github-workflow",
    description="Check PR status",
    prompt="Get status for PR #45 - are checks passing and is it ready to merge?"
)
```

### Incorrect Usage (DO NOT DO THIS)

❌ **Incorrect - Using GitHub operations directly:**
```python
# NEVER DO THIS - These are BLOCKED:
Skill(command="github-operations")              # Will fail with permission error
Bash("gh pr create ...")                        # Blocked
Edit(".claude/skills/github-operations/...")    # Blocked - use agent
bash .claude/skills/github-operations/scripts/create-pr.sh "..." "..." "main" "..."
```

❌ **Incorrect - Creating branch without immediate push:**
```python
# NEVER DO THIS - Jira automation won't trigger
git checkout -b feature/TT-XXX-description
# ... then work on it later without pushing
```

### Branch Push Requirement

**CRITICAL:** All new branches MUST be pushed to remote **immediately** after creation.

**Why:** Triggers Jira automation (To Do → In Progress) and signals work has started.

**The github-workflow agent automatically enforces:**
1. Update main branch
2. Create feature branch
3. **IMMEDIATELY push to remote** (even if empty)
4. Then proceed with work

---

## Pull Request Standards

### Test Evidence Requirements

**CRITICAL:** When creating PRs, you MUST provide functional evidence for each acceptance criterion.

#### ❌ INSUFFICIENT: Test-only evidence
```
## Test Evidence
- ✅ test_load_json PASSED
- ✅ All 50 unit tests pass
```

#### ✅ REQUIRED: Functional evidence with production data
```
## Functional Evidence

### AC1: [Specific acceptance criterion from the Jira ticket]

**Real Example: [Demonstrating the feature with realistic data]**
```python
# Code showing feature working with production/realistic data
# Include concrete, measurable results
```

**Results:**
- ✓ [Specific outcome 1 with concrete details]
- ✓ [Specific outcome 2 with measurable results]
```

### Evidence Standards

For EVERY acceptance criterion, provide:

1. **Real Production/Realistic Data**
   - Use actual production data or realistic files (NOT test fixtures from `unit_tests/fixtures/`)
   - For file-based features: show file names, sizes, and processing results
   - For API/service features: show realistic requests/responses
   - For UI features: show actual user workflows with real data

2. **Actual Usage Workflows**
   - Demonstrate the feature working as specified in acceptance criteria
   - Show integration with existing systems works
   - Prove end-to-end workflows function correctly

3. **Concrete, Measurable Results**
   - Specific file names, sizes, or identifiers
   - Quantifiable outcomes (counts, durations, sizes)
   - Sample output data relevant to the feature

4. **End-to-End Verification**
   - Show feature works in application context
   - Verify dependencies actually work (import and use them)
   - Demonstrate configuration settings function

### PR Quality Assurance (MANDATORY)

After creating or updating any pull request, the github-workflow agent MUST:

1. **Re-read the PR** to verify it was created correctly
2. **Check completeness** against required sections:
   - Summary section present and meaningful
   - Related Jira Issue with clickable link
   - Acceptance Criteria with evidence for EACH AC
   - Test Evidence section
   - Changes Made section
3. **Fix any deficiencies** before reporting back
4. **Report confidence level** (✅ Complete or ⚠️ Needs attention)

This ensures PRs are properly documented and nothing is missed.

---

## Code Quality Standards

### Type Checking
- All code must pass type checking with zero errors
- Use strict type hints on all functions
- No `type: ignore` comments without justification

### Linting
- All code must pass `ruff check src/ unit_tests/`
- Follow project-specific ruff configuration
- No disabling of rules without documented reason

### Testing
- Unit tests are required but NOT sufficient for PR approval
- Tests must pass: `uv run pytest`
- Coverage target: 80%+ for new code
- Integration tests required for end-to-end features

### Pydantic Models
- Prefer `frozen=True` for immutable models
- Use `Field()` with descriptions for all fields
- Validate inputs with Pydantic validators where appropriate

---

## Development Guidelines

### Code Style
- Line length: 88 characters (Ruff)
- Use descriptive variable and function names without underscore prefixes for private methods
- Type hints required (MyPy configured with relaxed settings for dynamic patterns)
- Universal tooling: Ruff handles linting, formatting, and import sorting

### Module Structure
- Models in dedicated files (Pydantic models in `messaging/models/`)
- Services separated by responsibility (`connections/`, `providers/`, `messaging/`)
- Configuration managed via environment variables and Pydantic Settings
- Analytics and visualization components in `analytics/` subdirectories

### Key Patterns
- Async/await for WebSocket connections and data processing
- Dependency injection using the `injector` library
- Event-driven architecture with typed message routing
- Polars DataFrames for high-performance data processing
- Context managers for resource management (connections, subscriptions)

### Testing
- Tests located in `unit_tests/` directory
- Use **functional pytest style** (plain `def test_*` functions, NOT class-based `TestFoo`)
- Use pytest with async support (`pytest-asyncio`)
- Mock external dependencies (`pytest-mock`)
- Coverage reporting available (`pytest-cov`)

---

## Development Workflow

### When Implementing Features

1. **Read the acceptance criteria carefully**
   - Understand what "done" means
   - Identify what production data to use for verification

2. **Implement the feature**
   - Follow protocol-based design
   - Add type hints
   - Write unit tests

3. **Verify with production data**
   - Run actual workflows
   - Document concrete results

4. **Create PR with functional evidence**
   - Show each AC met with real examples
   - Provide file names, sizes, counts
   - Demonstrate downstream workflows work

### Branch-Based Development (Enforced)

- ❌ NEVER work on `main` branch - github-workflow agent will REJECT operations
- ✅ ALWAYS create feature branch: `git checkout -b feature/TT-XXX-description`
- ✅ MUST include Jira ticket (TT-XXX) in branch name - enforced by agent
- ✅ Push immediately after branch creation: `git push -u origin <branch>`

**Why Enforcement**: Rules are enforced in code (github-workflow agent), not documentation. Violations are impossible - the agent blocks them with clear error messages guiding you to the correct workflow.

### Git Commit Messages

- **Format**: `TT-XXX: Brief description of changes`
- **Capitalize first word**: Use imperative mood ("Add" not "Added")
- **Jira ticket required**: Every commit must reference a Jira ticket
- **Multiline allowed**: First line (summary) + optional detailed body
- **No generated signatures**: Don't add "Generated with Claude Code" or similar
- **No emojis** in commit messages
- **No "Co-Authored-By: Claude"** lines
- **Examples**:
  - `TT-142: Refactor WebSocket connection handling`
  - `TT-149: Add automatic reconnection logic`
  - `TT-87: Fix message routing for malformed events`

**Detailed format** (when needed):
```
TT-XXX: Brief description (max 72 chars)

Detailed explanation of what changed and why.

- Bullet point for specific change 1
- Bullet point for specific change 2
```

---

## Issue Resolution

### When You Encounter Issues

1. **Run tests first**
   ```bash
   uv run pytest
   uv run mypy .
   uv run ruff check .
   ```

2. **Test with realistic data appropriate to the feature**
   ```python
   # Use realistic data relevant to what the feature does
   result = await feature.process(realistic_input)
   ```

3. **Document the issue**
   - What file/data caused it?
   - What was expected vs actual?
   - Can it be reproduced?

4. **Report with evidence**
   - Show actual error messages
   - Provide file names and sizes
   - Include steps to reproduce

---

## Working with Claude Code

### Agent Workflow

**See "⚠️ CRITICAL: Mandatory Agent Usage" section at the top of this file for complete requirements.**

Quick reference:
- **Jira operations** → `Task(subagent_type="jira-workflow", ...)`
- **GitHub operations** → `Task(subagent_type="github-workflow", ...)`

### Essential Context Files
1. **This file** - Project context and decisions
2. **`pyproject.toml`** - Project configuration
3. **`docs/`** - Additional documentation if present

### Development Commands
```bash
# Code Quality
uv run mypy .
uv run ruff check .
uv run ruff format .

# Testing
uv run pytest
uv run pytest --cov

# Setup (if needed)
uv sync --dev
```

### Common Prompts
```bash
# Example effective prompts:
"Implement the feature described in TT-XXX"
"Create unit tests for the MessageRouter"
"Add error handling for malformed WebSocket messages as specified in the Jira ticket"
```

---

## Development Container Guidelines

- Anything you do in this environment must be reflected in the dev container.
- If you need to run Python code locally please use `uv venv` along with the appropriate python version.

---

## Questions?

If unclear about evidence requirements:
1. Ask the user for clarification

**Remember:** Test evidence ≠ Functional evidence. Show the feature working with real production data.
