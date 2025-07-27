# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- Script entry points available in `src/tastytrade/scripts/`

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
- Use pytest with async support (`pytest-asyncio`)
- Mock external dependencies (`pytest-mock`)
- Coverage reporting available (`pytest-cov`)

### Commit Guidelines
- Keep commit messages concise and descriptive
- No emojis in commit messages
- No "Co-Authored-By: Claude" lines
- Use conventional commit format when appropriate

## Development Container Guidelines
- Anything you do in this environment must be reflected in the dev container.
