# Changelog

All notable changes to this project, organized by sprint and grouped by ticket. Work predating the Jira migration (first Jira ticket landed Jan 20, 2026) is reconstructed from git history and grouped by theme at the end.

---

## Sprint 11 — GEX Snapshots & DXLink Handshake Hardening (May 17–24, 2026)

### TT-147: Migrate charting frontend to Lightweight Charts v5

- Migrate `charting/static/index.html` from Lightweight Charts v4.2 to v5 (frontend-only); collapse the two-chart resize hack into one chart with a native MACD pane, replace level-line workarounds with `createPriceLine`, drop the CSS branding hack via `layout.attributionLogo: false`
- Replace the HMA segment-series with a custom `HmaPrimitive` Series Primitive (direct canvas drawing) after the Custom Series API regressed; add `BoundedLineSegment` for time-bounded level lines
- Add a hierarchical Studies panel (Overlays vs Lower Panes) with group/child toggles; recolor prior-day OHLC
- Selected as the adopted charting path over the KLineChart prototype (TT-148)

### TT-141: Fix DXLink BAD_ACTION loop — handshake ordering and subscription caps

- Add `setup_done`, `authorized`, and per-channel `channel_opened` `asyncio.Event`s to `ControlHandler`; start the listener/router before any send and await each ack in protocol order (SETUP → AUTH_STATE:AUTHORIZED → CHANNEL_OPENED)
- `open_channels()` fans out CHANNEL_REQUESTs and gathers CHANNEL_OPENED events in parallel
- Classify `BAD_ACTION` errors so subscription-cap errors log a warning without triggering reconnect, while connection-level errors still recover
- Add a snapshot-gated candle subscription semaphore (default 18, `CANDLE_SUBSCRIPTION_CONCURRENCY`) with per-symbol completion via `CandleSnapshotTracker.wait_for_symbol`

### TT-139: GEX snapshot — backend data collection and computation

- Add `analytics/gex/` package: `client.py` (REST fetchers, ±10% strike pre-filter, batched option market-data), `compute.py` (`OI × γ × M × spot² × 0.01 × sign`, aggregate-by-strike), `levels.py` (call/put walls, max-gamma, net-gamma wall), `snapshot.py` (orchestrator with Redis cache)
- Class-aware multiplier (equity options = 100 in the resolver, never at the formula site); futures options raise `NotImplementedError` (post-v1)
- REST-only design — no DXLink streaming; ~3–4 REST calls plus Polars aggregation
- Verified against live SPX: 195 strikes, ±9.9% window, call wall 7500 / put wall 7375, Redis cache HIT on second call

### TT-138: GEX snapshot — REST-based market-structure design (parent story)

- Lock a REST-only architecture after an RTH liveness probe confirmed `/market-data/by-type` returns per-option gamma, Greeks, open-interest, and mark
- Adopt an on-demand, frontend-paced runtime with a Redis `gex:snapshot:<sym>:<exp>` side-cache (~60s TTL) and a flat ±10%-of-spot strike window
- Shipping code lands under sub-task TT-139 (backend); this story coordinates the design

### TT-137: Clean up pytest warnings from the pre-push hook

- Replace raw strings passed to `model_construct()` with typed values (`OrderType.LIMIT`, `TimeInForce.DAY`, tz-aware `datetime`) to clear 7 `PydanticSerializationUnexpectedValue` warnings
- Fix a never-awaited `RedisSubscription.listener` coroutine warning via a `create_task` mock side-effect that closes the orphaned coroutine
- Test-only changes; no `filterwarnings` suppressions added

---

## Sprint 10 — Plan-Review Portal & Plugin (Apr 12–26, 2026)

### TT-132: Remove unused keepalive_stop Event from DXLink keepalive

- Decline the proposed event-driven refactor after plan review — the existing `while True` + `asyncio.sleep(30)` keepalive is already cancellation-driven via `close()`
- Remove the unused `self.keepalive_stop = asyncio.Event()` field; leave `send_keepalives()`/`close()` behavior unchanged

### TT-128: Open-source the /plan-review skill as a Claude Code plugin

- Publish `/plan-review` as a standalone MIT-licensed plugin in the `xmandeng/claude-plugins` marketplace, following Anthropic's official plugin layout
- Decouple all paths via `${CLAUDE_PLUGIN_ROOT}`; bundle its own template/devserver assets with zero dependency on the tastytrade-sdk layout
- Default output to `.plan-review/` (overridable), add per-project port allocation and LAN-IP binding for cross-device review
- Generalize invocation beyond Jira (any tracker ID; zero-arg infers from conversation); stdlib `pty.fork()` PTY bridge with no required pip deps

### TT-127: Evolve plan-review into a living "Next Turn" planning portal

- After review, drop the originally-proposed `tastydev` daemon / SPA / CLI in favor of enriching the existing `/plan-review` HTML playground
- Add a `WS /api/claude` websocket endpoint to `_devserver.py` that spawns `claude --continue` in a PTY and bridges it to the browser
- Add an xterm.js terminal panel plus a "Send to Claude" button that writes the feedback bundle into the live session (revisions applied via the session's native Edit tool)

---

## Sprint 9 — Redis Streams & Stability Fixes (Apr 5–12, 2026)

### TT-124: Fix kaleido dependency for Apple Silicon

- Bump `kaleido` 0.1.0 → 0.2.1 (first release with a `macosx_11_0_arm64` wheel), fixing `uv sync` on M-series Macs

### TT-119: Fix broken dependencies, pre-commit hook, and duplicate LangSmith tracing

- Restore `fastapi>=0.115.8` removed by TT-48 dead-code cleanup while `charting/server.py` still imported it
- Resolve the pre-commit hook `INSTALL_PYTHON` path dynamically via `git rev-parse --show-toplevel` so it works across worktrees/devcontainers
- Add a yield-to-project guard in the global stop hooks to eliminate duplicate LangSmith traces

### TT-118: Update architecture docs for Redis Streams

- Update the Architecture Playground Redis node to "Pub/Sub + Hash Store + Streams" and document the fill-stream schema; verify ARCHITECTURE.md §4 after the TT-108 merge

### TT-115: Loosen Jade Lizard delta warning thresholds

- Raise the net-delta warning threshold from ±0.35 to ±0.40 and add an escalated threshold at ±0.50

### TT-109: Fix chart server crash on metadata-only InfluxDB rows

- Add a required-column check (`close`/`open`/`high`/`low`) so metadata-only rows are treated as no-data, eliminating `ColumnNotFoundError` and letting the day-walkback loop continue

### TT-108: Redis Streams for position lifecycle tracking

- Introduce Redis Streams as a session-scoped compute layer for fill-driven lifecycle tracking (InfluxDB remains the system of record); stream key `tastytrade:fills:{account}:{underlying}`
- Add `xadd_fill()`, `fill_stream_key()`, and `flush_fill_streams()` to `AccountStreamPublisher`; hydrate streams at startup from InfluxDB filled orders (DEL-then-hydrate for idempotency)
- Verified live: 189 fills hydrated across 8 underlyings spanning Oct 2025 – Mar 2026, restart-identical streams, clean flush at shutdown

---

## Sprint 8 — Live Charting, Order Analytics & Agentic Infrastructure (Mar 15–29, 2026)

### TT-107: Guard empty InfluxDB results in MarketDataProvider.download

- Return an empty Polars DataFrame on an empty `query_data_frame()` result instead of accessing `d["_time"]`, eliminating a `KeyError` that killed chart sessions and restoring the day-walkback fallback

### TT-106: Implement MCP subagent architecture via Bifrost gateway

- Run MCP servers as persistent containerized services behind Bifrost gateways, with subagents communicating over HTTP curl — bypassing Claude Code's broken in-frontmatter subagent MCP wiring (see TT-105)
- Add two docker-compose Bifrost clusters with healthchecks: a dev cluster (port 3001) hosting GitHub MCP + Jira/Atlassian MCP (`sooperset/mcp-atlassian`), and a design cluster (port 3002) hosting Playwright MCP
- Add a generator script that builds subagent `.md` definitions from the live gateway `tools/list` manifest
- Document the architecture in `docs/AGENTIC_CONFIGURATION.md`; add response-size management (default `per_page: 5`) to keep list responses under the read limit
- Validated end-to-end via Bifrost curl: GitHub PR listing, Jira boards→sprints→issues chaining, and Playwright chart navigation/screenshot

### TT-105: (Reverted) Attempt to migrate subagents to inline MCP servers

- Tried to replace bash-script-wrapped subagents with inline `mcpServers` in agent frontmatter; verified both servers start (49 Jira tools, 39 GitHub tools)
- Blocked by Claude Code bug #25200 — MCP tools declared in agent frontmatter are never injected into the subagent runtime — so the branch was reverted; superseded by the Bifrost-gateway approach in TT-106

### TT-104: Fix irregular chart time labels in EXT mode

- Snap post-last-candle padding to the next clean hour/half-hour boundary so auto-generated axis ticks land on round, evenly spaced intervals (follow-up to TT-103)

### TT-103: Fix extended-hours chart squashing candles

- Compute x-axis bounds from the actual candle timestamp range instead of hardcoded regular-trading-hours anchors, so pre-market/RTH/after-hours sessions all render readably

### TT-101: Auto-subscribe candles for position-derived underlyings

- Create Candle subscriptions (not just Quotes) for resolver-discovered underlyings using the configured intervals; surface them in the chart symbol dropdown; remove on position close

### TT-100: Auto-subscribe to underlying symbols for option positions

- Extend `PositionSymbolResolver.resolve()` to include each position's `underlying-symbol` in the DXLink subscription set, deduped across shared underlyings and removed on close — for both futures and equity options

### TT-99: Interactive chart controls — symbol/interval/date pickers

- Replace static toolbar inputs with custom dark-theme dropdowns; add a server API serving the active candle-symbol list; wire control changes to a clean WebSocket reconnect

### TT-98: Add RedisInsight to the Docker Compose stack

- Add a `redis/redisinsight` service auto-connecting to Redis via internal DNS, exposed on port 5540 for browser-based pub/sub inspection (no more SSH tunneling)

### TT-97: Fix connection health status stuck after reconnect

- Publish `state: connected` and clear the stale `error` field on `tastytrade:connection` after the subscription orchestrator successfully reconnects

### TT-94: Live Charting Module — TOS-style interactive chart

- Add the `charting/` module: candlesticks + Hull MA-20 + MACD (12/26/9) in a separate pane, rendered via TradingView lightweight-charts with incremental `series.update()`
- Load history from InfluxDB on connect and stream live candle deltas from Redis pub/sub (historical → InfluxDB, live → Redis)
- Ship a `tasty-chart` CLI; source horizontal levels from a separate `LevelAnnotationProcessor` rather than the charting server (thin pass-through)

### TT-91: Add campaign P&L view to the chains CLI

- Aggregate realized losses from prior rolls and net them against current open mark value to show true campaign P&L and "recovery needed"; add an `--underlying` filter and a `--detail` roll-history view

### TT-90: Fix Iron Butterfly / Iron Broken Fly P&L dispatch

- Add both strategy types to `compute_max_profit`/`compute_max_loss` so their max-profit/max-loss columns populate instead of falling through to `None`

### TT-89: Options chain snapshot tool with DTE filtering

- Add a unified equity/futures option-chain fetcher returning a consistent Polars schema, auto-detecting asset class by symbol prefix; closest-match DTE filtering; `tasty-subscription options` CLI

### TT-88: Fix future-option multiplier source

- Read the contract multiplier from the option instrument's own `multiplier` field instead of the underlying future's `notional-multiplier`, fixing future-option dollar metrics that were 100x too small when the underlying wasn't held

### TT-87: Compute entry credits from order fill data

- Compute entry credits directly from fill prices/quantities/actions in the FILLED order event, removing the REST transactions API, Redis position-quantity lookups, and the race with the position consumer
- Add `resolve_multiplier` and `compute_leg_entry_credit`; add max-profit/loss formulas for broken-fly and butterfly strategies

### TT-86: Enrich order events with execution Greeks

- Add `extract_execution_greeks(chain)` walking each `lite_nodes` `market_state_snapshot`; write per-leg `ExecutionGreeks` and aggregate `ExecutionGreeksAggregate` points to InfluxDB at event time (no new consumers or Redis lookback)

### TT-85: Share one TelegrafHTTPEventProcessor across subscription handlers

- Replace 7 per-handler InfluxDB processor instances with one shared injected instance (cutting connection pools, retries, and buffers 7x→1x)
- Add a remove-before-close shutdown pattern yielding exactly one flush/close on shutdown

### TT-84: Backfill historical account events into InfluxDB

- One-shot idempotent backfill of PlacedOrder/TradeChain/PlacedComplexOrder from the REST API and EntryCredit via LIFO replay, reusing TT-83 serialization; seed current position/balance snapshots from Redis

---

## Sprint 7 — Strategy Matchers & Account-Event Persistence (Mar 8–15, 2026)

### TT-83: Wire account stream events into InfluxDB

- Route 5 account event types (orders, complex orders, trade chains, positions, entry credits) through the shared `TelegrafHTTPEventProcessor` alongside the Redis path (balances excluded as high-volume)
- Add an `InfluxMixin.for_influx()` that flattens models and JSON-serializes nested `INFLUX_JSON_FIELDS`; replace `while True` consumer loops with event-driven cancellation

### TT-82: Add Broken Wing Butterfly strategy matchers

- Add `CALL_BWB`, `PUT_BWB`, and `IRON_BWB` strategy types and matchers (1:2:1 ratio, unequal wing spacing) so BWBs classify as single strategies instead of decomposing
- Tighten `match_iron_butterfly` to require equal wings; order BWB matchers after standard butterflies

---

## Sprint 6 — Entry Price Reconciliation (Mar 7–9, 2026)

### TT-81: Fix subscription reconnection after DXLink auth expiry

- Fix `DXLinkManager` singleton guard: `hasattr(self, "initialized")` always returned True (even when False), preventing re-initialization on reconnect — changed to `getattr(self, "initialized", False)`
- Convert `RedisEventProcessor` from synchronous `redis.Redis` to async `redis.asyncio.Redis` — synchronous calls were blocking the asyncio event loop during `publish()` and `hset()`
- Move `EventHandler.stop_listener` from class variable (shared across all instances) to instance variable — class-level sharing caused cross-instance interference during reconnect teardown
- Reset singleton state (`instance = None`) in `DXLinkManager.close()` and `MessageRouter.close()` for clean reconstruction
- Orchestrator explicitly resets `DXLinkManager.instance = None` before reconnect construction
- Fix closed positions not triggering DXLink unsubscription — `publish_position()` now publishes `CurrentPosition` event for all updates including closures (qty=0), so `PositionSymbolResolver` can diff and unsubscribe stale symbols
- Remove all `ge=0` / `ge=-1` / `le=1` Pydantic constraints from inbound event models (`TradeEvent`, `QuoteEvent`, `GreeksEvent`, `ProfileEvent`, `SummaryEvent`, `CandleEvent`) — brokerage data must not be rejected at the ingestion layer

### TT-79: Live-fill entry credit updates for option positions

- Subscribe to `tastytrade:events:Order` Redis pub/sub to react to filled orders in real time
- Extract option symbols from filled order legs (equity options + future options)
- Re-fetch transactions and recompute entry credits via LIFO replay on each fill
- Clean up entry credits for fully closed positions (quantity == 0)
- Dedicated Redis client for pub/sub isolation from the publisher's connection
- Non-fatal exception handling: malformed messages, network errors, and unexpected exceptions are logged and skipped

### TT-63: Entry price reconciliation via transaction LIFO replay

- Add `TransactionsClient` for fetching option transactions from REST API
- Implement LIFO replay algorithm (`compute_entry_credits_for_positions`) for entry credit computation
- Add `EntryCredit` model with value, method, and transaction count
- Compute entry credits at startup for all open option positions
- Publish entry credits to Redis HSET + pub/sub for downstream consumers
- Support equity options and future options uniformly

---

## Sprint 5 — Account Streamer Hardening (Mar 4–6, 2026)

### TT-77: Update plan review HTML files and review template

- Update review template (`review-template.html`) with improved layout and review-saving capabilities
- Update existing review files (TT-60, TT-62, TT-63, TT-64) to match new template format
- Fix whitespace alignment in TT-65 plan ASCII diagrams

### TT-76: Change all inbound Pydantic models to extra="allow"

- Position model was rejecting `update-type` field from brokerage, silently dropping 14 events at market close
- Change `TastyTradeApiModel`, `BaseEvent`, and `ORDER_MODEL_CONFIG` from `extra="forbid"`/`"ignore"` to `extra="allow"`
- All inbound brokerage data is now preserved on `model_extra` — reject nothing, discard nothing
- Remove defensive column-filtering in market provider that was gatekeeping data unnecessarily
- Document design rule in ARCHITECTURE.md: inbound brokerage models must use `extra="allow"`

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
- Add `STREAMING_SERVICES.md` operations guide

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

---

## Pre-Jira History — GitHub Issues Era (Nov 2024 – Jan 2026)

_Before the project migrated to Jira (the first Jira ticket, TT-6, landed Jan 20, 2026), work was tracked through GitHub pull requests. Reconstructed from git history and grouped by theme rather than ticket; parenthetical numbers are PR numbers._

### DXLink streaming foundation (Nov 2024)

- Initial MVP: async WebSocket setup, DXLink connection, message handler, config dataclass, and feed processing (#2–#6)
- Consolidate channel handlers and event handlers; add Pydantic models for sessions and consolidate session configurations (#12–#16)

### Model & messaging refinement (Jan 2025)

- Add event-time attributes; reorganize and refine market-data models; simplify messaging and configuration; add the DXLink manager (#18–#22)

### Data pipeline & observability (Feb 2025)

- CPU performance improvements and candlestick events (#23–#24)
- Introduce InfluxDB, devcontainer configuration, and Grafana (#37–#39)
- Add the data provider service and data access object; market provider enhancements (#43–#48)

### Charting & plotting (Feb–Mar 2025)

- Extend plot range; draw horizontal and vertical lines; add opening range (#49–#52)
- Reduce x-axis labels to 30-min; calibrate devtools for DST; live plot updates (#66–#69)

### Redis bus & service scaffolding (Mar 2025)

- Add Redis cache and `SubscriptionStore`; add `ConfigurationManager`; Redis pub/sub `EventProcessor` and pub/sub market data (#53–#60)
- Add driver scripts, FastAPI endpoints, and futures candle-regex parsing (#63–#65)

### Tooling transition (Jul 2025 – Jan 2026)

- Integrate Claude Code (#70); add devcontainer dotfiles, `uv`, and typing/stub cleanup
- Sparse maintenance through late 2025, then a "long overdue update sync" and devcontainer build fixes in Jan 2026 immediately preceding the Jira migration

> **GitHub → Jira transition:** The repository's first commit was Nov 9, 2024. Active PR-tracked development ran through mid-2025, tapered over the second half of 2025, and resumed under Jira on Jan 20, 2026 (TT-6). Entries above this point in the changelog are tracked by Jira ticket; entries below are reconstructed from PR history.
