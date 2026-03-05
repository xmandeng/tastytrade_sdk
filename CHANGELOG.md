# Changelog

All notable changes to this project, grouped by Jira ticket and organized by sprint.

---

## Sprint 5 — Account Streamer Hardening (Mar 4–5, 2026)

### TT-74: Fix devcontainer environment variable injection

- Fix `runArgs --env-file` silently ignored when using `dockerComposeFile`
- Add `env_file: ../.env` to docker-compose.yml as the canonical injection path
- Add `.env` self-sourcing to Claude Code hooks for Docker container compatibility

### TT-71: Add failure simulation listener to account streamer

- Add Redis pub/sub listener on `account:simulate_failure` channel
- Trigger reconnection via shared `ReconnectSignal` (not streamer internals)
- Mirrors the subscription streamer's `subscription:simulate_failure` pattern

### TT-70: Add Redis connection status updates to account streamer

- Publish connection health to `tastytrade:account_connection` HSET
- Track state (connected/disconnected), timestamp, and error details
- Mirrors subscription streamer's `tastytrade:connection` status pattern

### TT-69: Normalize net_delta to per-position (1x) scale

- Scale net_delta by contract multiplier for consistent cross-instrument comparison

### TT-68: Enable Grafana Cloud observability for account-stream command

- Wire OpenTelemetry tracing into the account-stream CLI entry point

### TT-67: Add instrument-type-dispatched symbol parsers for log formatting

- Type-safe symbol parsing per instrument type (equity, option, future, crypto)
- Clean log output without raw streamer symbol noise

### TT-65: Refactor AccountStreamer to use shared ReconnectSignal

- Remove embedded reconnection state (`reconnect_event`, `should_reconnect`, `reconnect_reason`)
- Remove `trigger_reconnect()` and `wait_for_reconnect_signal()` methods
- Accept injected `ReconnectSignal` from orchestrator — same pattern as subscription streamer
- Orchestrator creates signal once, passes to streamer and failure listener

### TT-66: Add dynamic calendar-day lookback on reconnect

- Derive lightweight `start_date` from Redis subscription store on reconnect
- Scope lookback to session symbols only (multi-host safe)
- Use `get_all_subscriptions` to read pre-teardown timestamps
- Fall back to yesterday midnight instead of original start_date

---

## Sprint 4 — Strategy Engine & Order Pipeline (Feb 28 – Mar 4, 2026)

### TT-64: Refactor reconnection signaling to event-driven state machine

- Introduce `ReconnectSignal` in `connections/signals.py` — stable mailbox across reconnect cycles
- Route all failure sources through Queue[0] → ControlHandler → ReconnectSignal
- Remove callback-based reconnection from DXLinkManager
- Single signal path: failure → Queue[0] → ControlHandler → ReconnectSignal → Orchestrator

### TT-62: Add strategy engine — deterministic strategy classification (21 commits)

- Add `StrategyClassifier` with greedy pattern matching (iron condor, vertical spread, jade lizard, etc.)
- Add `StrategyHealthMonitor` for DTE warnings and delta drift detection
- Add instrument models (`EquityOptionInstrument`, `FutureInstrument`, etc.) and `InstrumentsClient`
- Add `strategies` CLI command and justfile recipes
- Enrich positions with instrument details (multiplier, expiration, strike)
- Apply contract multiplier to max P&L for dollar amounts

### TT-61: Add position summary with strategy identification (6 commits)

- Add `positions-summary` recipe with pre-aggregated Python output
- Add Claude-powered strategy identification prompt
- Tighten strategy prompt — no reasoning output, add jade lizard variant

### TT-60: Add Order and ComplexOrder event pipeline (6 commits)

- Add order and complex order consumers to account stream orchestrator
- Promote order event logging from debug to info with actionable detail
- Add instrument-type-dispatched symbol parsers for log formatting
- Remove underscore prefixes from method and function names (codebase-wide)

---

## Sprint 3 — Position Metrics Pipeline (Feb 26, 2026)

### TT-59: Event-driven account streaming and position metrics (26 commits)

- Add `AccountStreamPublisher` for positions/balances to Redis HSET + pub/sub
- Add `PositionSymbolResolver` — event-driven position → DXLink subscription via Redis pub/sub
- Add `PositionMetricsReader` — joins positions + quotes + Greeks from Redis
- Add account stream orchestrator with self-healing reconnection and exponential backoff
- Add HSET storage to `RedisEventProcessor` for latest market data
- Refactor position resolver from polling to event-driven (pub/sub listener)
- Remove PII from logging output (account numbers, balances)
- Add `streaming_services.md` operations guide

---

## Sprint 2 — Signal Service & Architecture (Feb 20–26, 2026)

### TT-58: Architecture playground enhancements

- Add Ctrl+C copy metadata as JSON

### TT-57: Claude Code workflow configuration (5 commits)

- Add Claude Code permission settings to version control
- Add layout management improvements to architecture playground

### TT-56: Signal service refactor — Redis-as-bus pattern (9 commits)

- Replace callbacks with Redis pub/sub at service boundaries
- Add `EngineRunner` harness with event-driven subscription
- Add `TradeSignalFeed` — reuse EngineRunner as InfluxDB sink
- Add `EventPublisher` protocol — engines own their own publisher
- Add design maxims: no unbounded loops, event flow over callbacks
- Add signal architecture documentation

### TT-55: Interactive architecture concept map

- Add architecture playground (self-contained HTML, no build step)
- Add movable panels, autosave, and author-branded insights

### TT-54: Market holiday walkback for daily candles

- Add walkback logic to `get_daily_candle` for market holidays

### TT-53: Docker-native service discovery (4 commits)

- Layered service discovery: `os.environ` → Redis → code defaults
- Docker Compose `environment` overrides for container networking
- Document service discovery in `docs/SERVICE_DISCOVERY.md`

### TT-51: InfluxDB configuration fix

- Fix `TelegrafHTTPEventProcessor` configuration initialization
- Remove `os.environ` fallbacks from InfluxDB configuration

### TT-43: Backtesting framework (8 commits)

- Add multi-timeframe Redis pipeline for historical replay
- Add `BacktestRunner` with signal + pricing candle subscription
- Add `BacktestPublisher` for entry/exit pricing enrichment
- Fix DXLink interval normalization and persistence contract violation
- Fix shutdown race condition and end_date boundary

---

## Sprint 1 — Infrastructure & Observability (Feb 5–21, 2026)

### TT-47: OAuth2 authentication migration

- Add `AuthStrategy` protocol with DI for environment-aware auth
- Migrate from session-token to OAuth2
- Add `OAuth2AuthStrategy` and `LegacyAuthStrategy` implementations

### TT-46: Signal detection service

- Replace synchronous signal callbacks with Redis pub/sub publisher
- Add typed deserialization and standalone signal service CLI
- Add observability to signal service

### TT-45: WebSocket token expiry reconnection fix

- Fix response validation ordering and exception construction

### TT-41: Hull+MACD confluence signal engine

- Add `HullMacdEngine` — standalone state machine for signal detection
- Convert Hull MA from Pandas to Polars
- Add InfluxDB signal persistence
- Add signal architecture documentation

### TT-38: Daily candle convenience method

- Add `get_daily_candle()` to `MarketDataProvider`

### TT-37: Options position metrics (Greeks & IV)

- Add options metrics engine with Greeks channel support
- Fall back to symbol for equities with no streamer_symbol

### TT-36: Chart annotation persistence

- Persist chart annotations to InfluxDB
- Rebase annotations on `BaseEvent`, remove standalone persistence

### TT-31: Delta-1 position metrics engine

- Add `MetricsTracker` for real-time position metrics

### TT-29: Account Streamer SDK (10 commits)

- Add `AccountStreamer` WebSocket manager (singleton)
- Add `AccountEventType` enum and streamer protocol models
- Add structured logging with Grafana observability
- Account number obfuscation in all outputs

### TT-28: Account discovery and models (11 commits)

- Add `Account`, `Position`, `AccountBalance` models with REST client
- Add account discovery notebook for API field validation

---

## Foundation (Jan 20 – Feb 9, 2026)

### TT-32: Test reorganization

- Reorganize `unit_tests/` to mirror `src/tastytrade/` module structure

### TT-27: LangSmith integration for Claude Code

- Add session monitoring hooks
- Fix ARG_MAX error in hook scripts

### TT-26: Claude Code configuration

- Add LangSmith integration, consolidate permission settings

### TT-25: Redis pub/sub failure simulation

- Add Redis trigger for simulated WebSocket failures
- Add comprehensive unit tests for reconnection workflow

### TT-24: Reconnection logic and failure simulation

- Fix reconnection edge cases

### TT-23: Grafana Cloud observability

- Add OpenTelemetry observability module and documentation

### TT-21: WebSocket connection recovery

- Add error-based health status reporting

### TT-20: Implementation standards

- Add completion documentation standards
- Fix `last_update` tracking and `AUTH_STATE` handling
- Remove staleness check, handle DXLink errors

### TT-19 and earlier: CLI scaffold and core infrastructure

- TT-19: Add justfile recipes
- TT-18: Fix root logger usage, reduce log verbosity
- TT-17: Add periodic health status logging
- TT-16: Downgrade misleading "Fatal error" log
- TT-15: Add session-scoped subscription cleanup
- TT-14: Add PR quality assurance standards, flush InfluxDB on shutdown
- TT-13: Add CLI documentation
- TT-11: Implement status command for Redis subscription state
- TT-8: Add CandleSnapshotTracker, progress logging, timeout handling
- TT-7: Extract notebook logic into importable orchestrator
- TT-6: Add `tasty-subscription` CLI scaffold with Click
