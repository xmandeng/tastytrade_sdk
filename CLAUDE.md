# CLAUDE.md

## Core Principles

1. **Evidence-Based Development** — demonstrate with real production data, not just tests
2. **Protocol-Based Design** — use protocols (abstract interfaces) over concrete implementations
3. **Type Safety** — strict type checking with MyPy/Pyright
4. **Immutability** — frozen Pydantic models where possible
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

### No Exceptions

Direct calls are **intentionally blocked**. If you get "Skill execution blocked by permission rules", you violated this requirement.

See [docs/jira_workflow.md](docs/jira_workflow.md) and [docs/github_workflow.md](docs/github_workflow.md) for detailed examples.

---

## Development Environment & Commands

This project uses **UV** for dependency management in a dev container with pre-configured services.

### Setup
- `uv sync --dev` — install all dependencies (including dev)
- `docker-compose up -d` — start infrastructure services
- `cp .env.example .env` — copy environment template

### Code Quality
- `uv run ruff check .` — lint
- `uv run ruff format .` — format
- `uv run mypy .` — type check

### Testing
- `uv run pytest` — run all tests
- `uv run pytest --cov` — with coverage
- `uv run pytest -v` — verbose

### Application
- `uv run api` — start FastAPI server
- `uv run tasty-subscription run --start-date 2026-01-20 --symbols SPY,AAPL --intervals 1d,5m` — market data CLI

See [docs/subscription_cli.md](docs/subscription_cli.md) for full CLI reference.

---

## Architecture Overview

High-performance Python SDK for TastyTrade's Open API with real-time market data processing.

### Data Flow Pipeline

1. **DXLinkManager** (`src/tastytrade/connections/sockets.py`) — WebSocket connection management
2. **MessageRouter** (`src/tastytrade/messaging/`) — event parsing, routing, processing
3. **Data Storage** — InfluxDB (time-series), Redis (pub/sub)
4. **Analytics Engine** (`src/tastytrade/analytics/`) — indicators, visualizations, charts

### Key Modules

- `src/tastytrade/connections/` — API connections, WebSocket management, subscriptions
- `src/tastytrade/messaging/` — event models, message processing, routing
- `src/tastytrade/providers/` — market data providers, subscription management
- `src/tastytrade/analytics/` — technical indicators, charting, visualizations
- `src/tastytrade/dashboard/` — interactive dashboards (Dash/Plotly)
- `src/tastytrade/config/` — configuration management, enumerations
- `src/tastytrade/common/observability.py` — non-blocking logging (JSON stdout + OTLP to Grafana Cloud)

### Architecture Docs

- [docs/trading_observability_spec_FINAL.md](docs/trading_observability_spec_FINAL.md) — observability design
- [docs/GITHUB_WORKFLOW_SPEC.md](docs/GITHUB_WORKFLOW_SPEC.md) — GitHub workflow spec
- [docs/ISSUES_SPEC.md](docs/ISSUES_SPEC.md) — issue management spec

### Infrastructure Services (docker-compose)

- **InfluxDB** (8086) — time-series storage
- **Redis** (6379) — message queue / caching
- **Telegraf** (8186) — data collection / routing
- **Grafana** (3000) — monitoring dashboards
- **Redis-Commander** (8081) — Redis management UI

### Observability

Non-blocking queue-based logging: JSON to stdout + OTLP export to Grafana Cloud. Works with standard `logging.getLogger()` — no code changes needed. See [docs/trading_observability_spec_FINAL.md](docs/trading_observability_spec_FINAL.md).

---

## Workflow Rules

### Jira Operations — MANDATORY DELEGATION

You MUST delegate ALL Jira operations to the jira-workflow agent. No exceptions.

**Operations:** create/update/search/comment on tickets, get details, link to Epics.

**Verbatim Content Rule:** When passing plans or implementation details to jira-workflow, include:
> "Use the following content VERBATIM. Do NOT paraphrase, summarize, or rewrite."

**Status transitions are automated** (branch → In Progress, PR → In Review, merge → Done). Do NOT manually transition.

**Epic governance:** Agent CAN link to Epics, CANNOT create Epics.

**Completion documentation:** When work is done, add implementation comment via jira-workflow with: Expected Behaviors (Before/After), Technical Implementation, Features, Verification Evidence.

**Quality assurance:** After every ticket update, jira-workflow MUST re-read and verify the ticket.

**Plan-ticket alignment:** Persist the full implementation plan to the ticket BEFORE starting work.

See [docs/jira_workflow.md](docs/jira_workflow.md) for examples, templates, and procedures.

### GitHub Operations — MANDATORY DELEGATION

You MUST delegate ALL GitHub operations to the github-workflow agent. No exceptions.

**Autonomous PR creation:** When all ACs pass and code is pushed → create PR immediately. Do NOT ask permission.

**Operations:** create/list/view PRs, create/push branches, repository operations, PR reviews.

**Branch push requirement:** All new branches MUST be pushed to remote IMMEDIATELY after creation (triggers Jira automation).

See [docs/github_workflow.md](docs/github_workflow.md) for examples and procedures.

### Pull Request Standards

**CRITICAL: Unit tests are NOT functional tests.** You MUST functionally test code before creating a PR.

- Run the code in a realistic environment and capture evidence
- Provide functional evidence for EACH acceptance criterion using real/production data
- If you cannot test: STOP, notify the user, do NOT create the PR

**PR quality assurance:** github-workflow agent MUST re-read and verify every PR after creation.

See [docs/pr_standards.md](docs/pr_standards.md) for templates and evidence standards.

### Branch & Commit Rules

**Branching:**
- NEVER work on `main` — github-workflow agent will REJECT operations
- ALWAYS create feature branch with Jira ticket: `feature/TT-XXX-description`
- MUST push immediately after creation: `git push -u origin <branch>`

**Commit format:** `TT-XXX: Brief description`
- Imperative mood ("Add" not "Added"), capitalize first word
- Jira ticket required in every commit
- No emojis, no generated signatures, no "Co-Authored-By: Claude"
- Examples: `TT-142: Refactor WebSocket connection handling`, `TT-87: Fix message routing for malformed events`

---

## Code Quality Standards

### Type Checking
- All code must pass type checking with zero errors
- Strict type hints on all functions
- No `type: ignore` without justification

### Linting
- Must pass `ruff check src/ unit_tests/`
- No disabling rules without documented reason

### Testing
- Unit tests required but NOT sufficient for PR approval
- Tests must pass: `uv run pytest`
- Coverage target: 80%+ for new code
- Integration tests required for end-to-end features

### Pydantic Models
- Prefer `frozen=True` for immutable models
- Use `Field()` with descriptions
- Validate inputs with Pydantic validators where appropriate

---

## Development Guidelines

### Code Style
- Line length: 88 characters (Ruff)
- Descriptive names, no underscore prefixes for private methods
- Type hints required (MyPy with relaxed settings for dynamic patterns)
- Ruff handles linting, formatting, and import sorting

### Module Structure
- Models in dedicated files (Pydantic models in `messaging/models/`)
- Services separated by responsibility (`connections/`, `providers/`, `messaging/`)
- Configuration via environment variables and Pydantic Settings
- Analytics/visualization in `analytics/` subdirectories

### Key Patterns
- Async/await for WebSocket connections and data processing
- Dependency injection using `injector` library
- Event-driven architecture with typed message routing
- Polars DataFrames for high-performance data processing
- Context managers for resource management

### Testing Style
- Tests in `unit_tests/` directory
- **Functional pytest style** (plain `def test_*`, NOT class-based `TestFoo`)
- pytest with async support (`pytest-asyncio`), mocking (`pytest-mock`), coverage (`pytest-cov`)

---

## Dev Container

- All environment changes must be reflected in the dev container
- Use `uv venv` with the appropriate Python version for local execution
