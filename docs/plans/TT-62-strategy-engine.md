# TT-62: Option Strategy Classification Engine — Implementation Plan

> **Jira:** [TT-62](https://mandeng.atlassian.net/browse/TT-62)

## Context

The current `positions-summary` property groups legs by underlying and shows net delta + leg count, but doesn't identify strategies — that's delegated to an LLM via `just positions-strategies`. This is slow, expensive, and sometimes wrong (misidentifying jade lizards as collars).

**Goal:** Build a deterministic strategy classifier that assembles all underlying positions, enriches them with broker-provided instrument metadata (strike, call/put, expiration), and classifies them into recognized option strategy recipes — including tastytrade varieties. Full lifecycle: identification, aggregate Greeks, P&L metrics, health monitoring.

**Key design decision:** Get option metadata from the TastyTrade API (`GET /instruments/equity-options`) instead of parsing OCC symbols locally. Persist instrument details to Redis so all consumers read structured data.

---

## Architecture Overview

```
TT API                    Redis                         Analytics
───────                   ─────                         ─────────
/instruments/             tastytrade:instruments        PositionMetricsReader
  equity-options  ──▶     (HSET: symbol → JSON)    ──▶   .strategies property
                                                          StrategyClassifier
/accounts/.../            tastytrade:positions              │
  positions       ──▶     (HSET: symbol → JSON)    ──▶   ParsedLeg objects
                                                          │
DXLink stream     ──▶     tastytrade:latest:*      ──▶   Greeks/Quotes
                                                          │
                                                        Strategy objects
                                                        (type, legs, Greeks, P&L, health)
```

**Data flow:**
1. Account-stream starts → hydrates positions from API → for each option position, batch-fetches instrument details from `GET /instruments/equity-options` → writes both to Redis
2. On live position updates (new option positions), fetches instrument details and writes to Redis
3. `PositionMetricsReader.read()` loads positions + instruments + quotes + Greeks from Redis
4. `StrategyClassifier` uses enriched data to identify strategies via greedy pattern matching

---

## Step 1: Instrument Models & Client

### Per-type instrument models

**File:** `src/tastytrade/market/models.py` (new)

Each model maps 1:1 to its TT API `/instruments/*` endpoint. All extend `TastyTradeApiModel` (frozen Pydantic).

```python
class OptionType(str, Enum):
    CALL = "C"
    PUT = "P"

class EquityOptionInstrument(TastyTradeApiModel):
    symbol: str                              # OCC symbol
    instrument_type: str                     # "Equity Option"
    strike_price: Decimal                    # e.g., 305.0
    option_type: OptionType                  # "C" or "P"
    root_symbol: str                         # e.g., "SPY"
    underlying_symbol: str                   # e.g., "SPY"
    expiration_date: date                    # YYYY-MM-DD
    days_to_expiration: int                  # computed by broker
    expires_at: datetime                     # full timestamp
    exercise_style: str                      # "American"
    settlement_type: str                     # "PM"
    shares_per_contract: int                 # 100
    streamer_symbol: str                     # ".SPY260220C185"
    active: bool
    is_closing_only: bool

class FutureOptionInstrument(TastyTradeApiModel):
    symbol: str                              # e.g., "./MESM6EX3H6 260320P6450"
    underlying_symbol: str                   # e.g., "/MESM6"
    product_code: str                        # e.g., "EX3"
    expiration_date: date
    strike_price: Decimal
    option_type: OptionType                  # "C" or "P"
    exchange: str                            # e.g., "CME"
    streamer_symbol: str                     # e.g., "./EX3H26P6450:XCME"

class EquityInstrument(TastyTradeApiModel):
    symbol: str
    instrument_type: str
    description: Optional[str]
    is_etf: bool
    active: bool

class FutureInstrument(TastyTradeApiModel):
    symbol: str
    product_code: str
    contract_size: Decimal
    notional_multiplier: Decimal
    expiration_date: date
    active: bool

class CryptocurrencyInstrument(TastyTradeApiModel):
    symbol: str
    instrument_type: str
    description: Optional[str]
    active: bool
```

### InstrumentsClient — one method per type

**File:** `src/tastytrade/market/instruments.py` (extend existing)

```python
class InstrumentsClient:
    def __init__(self, session: AsyncSessionHandler): ...

    async def get_equity_options(self, symbols: list[str]) -> list[EquityOptionInstrument]:
        """GET /instruments/equity-options?symbol[]={sym1}&symbol[]={sym2}..."""

    async def get_future_options(self, symbols: list[str]) -> list[FutureOptionInstrument]:
        """GET /instruments/future-options?symbol[]={sym1}&symbol[]={sym2}..."""

    async def get_equities(self, symbols: list[str]) -> list[EquityInstrument]:
        """GET /instruments/equities?symbol[]={sym1}&symbol[]={sym2}..."""

    async def get_futures(self, symbols: list[str]) -> list[FutureInstrument]:
        """GET /instruments/futures?symbol[]={sym1}&symbol[]={sym2}..."""

    async def get_cryptocurrencies(self, symbols: list[str]) -> list[CryptocurrencyInstrument]:
        """GET /instruments/cryptocurrencies?symbol[]={sym1}&symbol[]={sym2}..."""
```

**Batch size:** TT API may have URL length limits. Batch into groups of ~50 symbols per request.

---

## Step 2: Instrument Publisher (Redis persistence)

### Extend `AccountStreamPublisher`

**File:** `src/tastytrade/accounts/publisher.py`

Add a new Redis HSET key and publish method:

```python
INSTRUMENTS_KEY = "tastytrade:instruments"  # Single HSET, keyed by symbol

async def publish_instruments(self, instruments: list) -> None:
    """Write instrument details to Redis HSET. Key = symbol, value = JSON.

    Accepts any instrument model type (EquityOptionInstrument,
    FutureOptionInstrument, EquityInstrument, etc.).
    """
```

Single HSET is sufficient — symbol is globally unique across types, and consumers can look up by the Position's symbol field.

### Orchestrator integration

**File:** `src/tastytrade/accounts/orchestrator.py`

After `streamer.start()` and position hydration, create an `InstrumentsClient` using `streamer.session` and enrich all position types:

```
run_account_stream_once():
    await streamer.start()       # positions hydrated into queue

    # NEW: Enrich positions with instrument details per type
    instruments_client = InstrumentsClient(streamer.session)

    # Group position symbols by instrument type
    equity_option_syms = [p.symbol for p in positions if p.instrument_type == EQUITY_OPTION]
    future_option_syms = [p.symbol for p in positions if p.instrument_type == FUTURE_OPTION]
    equity_syms = [p.symbol for p in positions if p.instrument_type == EQUITY]
    # ... etc for futures, crypto

    # Batch-fetch from each endpoint
    instruments = []
    if equity_option_syms:
        instruments += await instruments_client.get_equity_options(equity_option_syms)
    if future_option_syms:
        instruments += await instruments_client.get_future_options(future_option_syms)
    if equity_syms:
        instruments += await instruments_client.get_equities(equity_syms)
    # ...

    await publisher.publish_instruments(instruments)

    # Continue with existing consume loops...
```

For live position updates: when `_consume_positions()` sees a new position not already in the instruments HSET, fetch and publish its instrument details using the appropriate type-specific method.

---

## Step 3: Strategy Models

**File:** `src/tastytrade/analytics/strategies/models.py`

### StrategyType enum (comprehensive)

| Category | Strategies |
|----------|-----------|
| Delta-1 | Long Stock, Short Stock, Long Crypto, Short Crypto |
| Single-leg | Long Call, Long Put, Naked Call, Naked Put |
| Covered | Covered Call, Protective Put, Collar |
| Verticals | Bull Call Spread, Bear Call Spread, Bull Put Spread, Bear Put Spread |
| Straddle/Strangle | Long/Short Straddle, Long/Short Strangle |
| Tastytrade | Jade Lizard, Covered Jade Lizard, Big Lizard |
| Iron | Iron Condor, Iron Butterfly |
| Butterfly/Condor | Call Butterfly, Put Butterfly, Condor |
| Calendar/Diagonal | Calendar Spread, Diagonal Spread |
| Other | Ratio Spread, Synthetic Long, Synthetic Short, Custom |

### ParsedLeg (frozen dataclass)

Built by joining `SecurityMetrics` + `EquityOptionInstrument` from Redis:

- Position fields: `streamer_symbol`, `symbol`, `underlying`, `instrument_type`, `signed_quantity`
- Instrument fields (from broker): `option_type`, `strike` (Decimal), `expiration` (date), `days_to_expiration`
- Market data fields: `delta`, `gamma`, `theta`, `vega`, `mid_price`

### Strategy (dataclass)

- `strategy_type`, `underlying`, `legs: tuple[ParsedLeg, ...]`
- Computed properties: `net_delta`, `net_gamma`, `net_theta`, `net_vega`
- P&L: `max_profit`, `max_loss`, `breakeven_prices` (strategy-type-specific formulas)
- Time: `days_to_expiration`, `nearest_expiration`
- `width` (strike width for spreads)

---

## Step 4: Pattern Matchers

**File:** `src/tastytrade/analytics/strategies/patterns.py`

Each pattern: `match_X(legs: list[ParsedLeg]) -> MatchResult | None`

**Priority order (greedy — most legs first):**

1. **4+ legs:** Iron Condor, Iron Butterfly, Covered Jade Lizard, Big Lizard, Butterfly, Condor
2. **3 legs:** Jade Lizard, Collar
3. **2 legs (with stock):** Covered Call, Protective Put
4. **2 legs (same exp, same type):** Vertical spreads, Ratio Spread
5. **2 legs (same exp, diff type):** Straddle, Strangle, Synthetic
6. **2 legs (diff exp):** Calendar, Diagonal
7. **1 leg:** Long/Short Stock, Long/Short Call/Put, Naked Call/Put

**Key matching rules:**
- All legs in a pattern must have matching absolute quantities (except ratio spreads)
- Straddle = same strike; Strangle = different strikes
- Iron condor = put strikes < call strikes, short inner + long outer
- Jade lizard = short OTM put + bear call spread (short call + long higher call)
- Quantity handling: 3 short puts + 1 short call → 1 strangle + 2 naked puts

---

## Step 5: Classification Engine

**File:** `src/tastytrade/analytics/strategies/classifier.py`

```
StrategyClassifier:
    classify(securities, instruments) -> list[Strategy]:
        1. Build ParsedLeg for each SecurityMetrics + instrument lookup
        2. Group by underlying_symbol
        3. For each underlying: greedy match patterns (most complex first)
        4. Consume matched legs, repeat until no more matches
        5. Remaining legs → single-leg strategies
```

---

## Step 6: Health Monitor

**File:** `src/tastytrade/analytics/strategies/health.py`
**Config:** `config/strategy_health.toml`

Thresholds are configurable per strategy type via TOML. Each strategy type can have its own thresholds, with a `[default]` section as fallback.

```toml
# config/strategy_health.toml

[default]
dte_warning = 21
dte_critical = 7
max_loss_warning = 0.75
max_loss_critical = 0.90
delta_drift_warning = 0.30

[iron_condor]
dte_warning = 30
dte_critical = 14
delta_drift_warning = 0.20

[short_strangle]
dte_warning = 25
dte_critical = 10
delta_drift_warning = 0.25

[jade_lizard]
delta_drift_warning = 0.35

# Strategies not listed here inherit from [default]
```

**HealthThresholds** loaded from TOML at startup. Key = `StrategyType` name in snake_case, value = threshold overrides merged with defaults.

```python
class StrategyHealthMonitor:
    def __init__(self, config_path: Path | None = None): ...
    def thresholds_for(self, strategy_type: StrategyType) -> HealthThresholds: ...
    def check(self, strategy: Strategy) -> list[HealthAlert]: ...
    def check_all(self, strategies: list[Strategy]) -> list[HealthAlert]: ...
```

### Future features — Jira ticket creation required (AC)

The following are out of scope for this ticket. **Acceptance criteria: create a Jira ticket for each** before closing this work.

- **Profit target tracking** — Track strategy P&L against a configurable profit target (e.g., close at 50% max profit)
- **Per-position adjustable thresholds** — Override health thresholds at the individual position/strategy level, not just by type
- **Position annotations** — User-defined notes/tags on positions (e.g., "rolling candidate", "earnings play")
- **InfluxDB persistence** — Store position/strategy snapshots as time-series data in InfluxDB for historical analysis

---

## Step 7: Integration

### PositionMetricsReader

**File:** `src/tastytrade/analytics/positions.py`

`read()` changes:
- Also load instruments from `tastytrade:instruments` Redis HSET
- Store `self.tracker` reference (currently only DataFrame is saved)
- Store `self.instruments: dict[str, EquityOptionInstrument]`

New properties:
- `strategies -> list[Strategy]` — calls `StrategyClassifier.classify()`
- `strategy_summary -> pd.DataFrame` — columns: underlying, strategy, legs, net_delta, net_theta, net_vega, dte, max_profit, max_loss, health, alerts

### CLI

**File:** `src/tastytrade/subscription/cli.py`

New `strategies` subcommand:
```
tasty-subscription strategies
tasty-subscription strategies --json
```

### Justfile

```just
strategies:
    uv run tasty-subscription strategies
```

---

## Module Structure

```
src/tastytrade/
    market/
        models.py              # NEW: OptionType, EquityOptionInstrument, FutureOptionInstrument,
                               #       EquityInstrument, FutureInstrument, CryptocurrencyInstrument
        instruments.py         # EXTEND: add InstrumentsClient (one method per type)
    accounts/
        publisher.py           # EXTEND: add INSTRUMENTS_KEY, publish_instruments()
        orchestrator.py        # EXTEND: instrument enrichment on startup + live updates
    analytics/
        positions.py           # EXTEND: strategies, strategy_summary properties
        strategies/
            __init__.py        # Public API exports
            models.py          # StrategyType, ParsedLeg, Strategy (~200 lines)
            patterns.py        # 25+ pattern matchers (~500 lines)
            classifier.py      # Greedy classification engine (~100 lines)
            health.py          # Health monitoring (~100 lines)

config/
    strategy_health.toml   # Per-strategy-type health thresholds

unit_tests/
    market/
        test_instruments_client.py   # InstrumentsClient tests
    analytics/
        strategies/
            test_patterns.py         # Per-pattern unit tests
            test_classifier.py       # End-to-end greedy matching tests
            test_health.py           # Health monitoring tests
```

---

## Critical File References

| File | Role |
|------|------|
| `src/tastytrade/accounts/orchestrator.py` | Integration point — instrument enrichment after startup |
| `src/tastytrade/accounts/publisher.py` | Redis writer — add instruments HSET |
| `src/tastytrade/market/instruments.py` | Existing instruments module — add InstrumentsClient |
| `src/tastytrade/analytics/metrics.py` | SecurityMetrics + MetricsTracker — input data |
| `src/tastytrade/analytics/positions.py` | PositionMetricsReader — new strategies properties |
| `src/tastytrade/accounts/models.py` | Position model, InstrumentType, QuantityDirection |
| `src/tastytrade/subscription/cli.py` | CLI commands — add `strategies` subcommand |
| `unit_tests/analytics/test_metrics_tracker.py` | Factory helpers to reuse |

---

## Verification

1. **Unit tests:** `uv run pytest unit_tests/analytics/strategies/ unit_tests/market/test_instruments_client.py -v`
2. **Type checking:** `uv run mypy src/tastytrade/analytics/strategies/ src/tastytrade/market/models.py`
3. **Linting:** `uv run ruff check src/tastytrade/analytics/strategies/`
4. **Functional test with live data:**
   - Start account-stream: `just account-stream` — verify instruments HSET populated in Redis
   - Run strategies: `just strategies` — verify strategies identified with broker-provided metadata
   - Cross-check against `just positions-strategies` (LLM-based) for accuracy
