# SPX 0DTE GEX Snapshot — Design Spec and Implementation Plan

## 1. Purpose

Build a point-in-time SPX 0DTE Gamma Exposure (GEX) snapshot using data available through the Tastytrade SDK.

This version is intentionally **not** a real-time trade-flow model. It is a start-of-day / periodic market-structure snapshot that uses observable option-chain metrics:

- SPX / SPXW 0DTE option chain
- Open interest
- Gamma
- SPX spot price
- Strike / expiration / call-put metadata

The goal is to produce a practical daily map of gamma concentration, likely support/resistance zones, and broad volatility regime.

---

## 2. Design Philosophy

The first version should optimize for:

- correctness
- explainability
- low operational complexity
- no OPRA dependency
- no trade-flow reconstruction
- no bid/ask aggressor inference

This avoids the hardest part of live GEX modeling: estimating intraday dealer inventory changes from trade flow.

The working question becomes:

> “Where is options gamma concentrated at the start of the day?”

Not:

> “How has dealer inventory changed second-by-second?”

---

## 3. Scope

### In Scope

- Fetch SPX / SPXW option chain
- Filter to 0DTE expirations
- Retrieve or stream gamma
- Retrieve open interest
- Retrieve current SPX spot price
- Compute GEX by option
- Aggregate GEX by strike
- Identify major gamma levels
- Render static snapshot chart
- Produce a short market-structure summary

### Out of Scope

- Full OPRA tape ingestion
- Tick-by-tick Time & Sales
- Trade aggressor classification
- Intraday dealer-position inference
- Order execution
- Automated trading
- Backtesting initially

---

## 4. Data Inputs

### 4.1 Option Chain

Required fields:

| Field | Purpose |
|---|---|
| option symbol / streamer symbol | subscription and lookup key |
| expiration date | identify 0DTE contracts |
| strike | aggregate exposure by strike |
| option type | call vs put |
| underlying | SPX / SPXW filtering |

### 4.2 Open Interest

Required for static GEX.

| Field | Purpose |
|---|---|
| open_interest | position-size proxy |

Open interest is generally stale intraday, but that is acceptable for a start-of-day snapshot.

### 4.3 Gamma

Required for GEX.

| Field | Purpose |
|---|---|
| gamma | per-option gamma exposure input |

Gamma may be queried from market metrics or streamed from DXLink Greeks, depending on what is most reliable in the local SDK workflow.

### 4.4 Spot Price

Required for exposure scaling.

| Field | Purpose |
|---|---|
| SPX spot | current index level |

---

## 5. Core Formula

For each option:

```python
gex = open_interest * gamma * contract_multiplier * spot_price**2 * 0.01 * sign
```

Where:

```python
contract_multiplier = 100
sign = +1 for calls
sign = -1 for puts
```

### Interpretation

- Positive call-side GEX suggests gamma concentration above/around strike.
- Negative put-side GEX suggests gamma concentration below/around strike.
- Net GEX by strike shows the combined effect of calls and puts.
- Total GEX gives a broad regime read.

---

## 6. Sign Convention

Use the common retail/internet convention:

```python
calls = positive
puts = negative
```

This is not a confirmed dealer-position truth. It is a convention for producing a useful options-positioning map.

Later versions may support alternate conventions:

- absolute gamma
- dealer-assumption gamma
- put/call separated gamma
- net gamma

The chart should make the convention explicit.

---

## 7. Data Model

### 7.1 Raw Option Row

```python
@dataclass
class OptionSnapshotRow:
    symbol: str
    streamer_symbol: str
    expiration: date
    strike: float
    option_type: Literal["C", "P"]
    open_interest: int
    gamma: float
    spot_price: float
```

### 7.2 Computed Option Row

```python
@dataclass
class OptionGexRow:
    symbol: str
    streamer_symbol: str
    expiration: date
    strike: float
    option_type: Literal["C", "P"]
    open_interest: int
    gamma: float
    spot_price: float
    gex: float
```

### 7.3 Aggregated Strike Row

```python
@dataclass
class StrikeGexRow:
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float
    abs_gex: float
```

---

## 8. Processing Pipeline

```text
Authenticate with Tastytrade
        ↓
Fetch SPX / SPXW option chain
        ↓
Filter to today's expiration
        ↓
Fetch or stream gamma and summary metrics
        ↓
Join chain + OI + gamma + spot
        ↓
Compute option-level GEX
        ↓
Aggregate by strike
        ↓
Identify major levels
        ↓
Render chart + text summary
```

---

## 9. Detailed Implementation Steps

### Step 1 — Authenticate

Create a production Tastytrade session.

Implementation detail:

- Keep credentials outside code.
- Use environment variables or a secrets manager.
- Do not run against sandbox for live market data assumptions.

---

### Step 2 — Fetch Option Chain

Fetch the SPX / SPXW option chain.

Filter:

```python
expiration == today
```

Optionally support:

```python
expiration in [today, next_expiration]
```

This allows comparison between pure 0DTE and near-dated structure.

---

### Step 3 — Normalize Symbols

Create a canonical lookup table:

```python
chain_df = [
    symbol,
    streamer_symbol,
    expiration,
    strike,
    option_type,
]
```

The `streamer_symbol` should be the key used for DXLink subscriptions.

---

### Step 4 — Fetch Spot Price

Fetch current SPX quote or equivalent index quote.

Store:

```python
spot_price = latest_spx_price
```

Fallbacks:

1. SPX quote
2. SPY-derived approximation
3. /ES-derived approximation

Prefer SPX directly where available.

---

### Step 5 — Retrieve Open Interest

Pull open interest from available summary / market metric data.

Expected field:

```python
open_interest
```

Rows without OI should be excluded or assigned zero.

Recommended:

```python
open_interest = open_interest.fillna(0)
```

---

### Step 6 — Retrieve Gamma

Preferred sources:

1. DXLink Greeks
2. Market metrics endpoint, if available and complete
3. Local Black-Scholes calculation as fallback

For v1, prefer Tastytrade-provided gamma to avoid IV/model discrepancies.

Rows without gamma should be excluded from GEX calculation.

---

### Step 7 — Compute Option-Level GEX

```python
def option_gex(row, spot_price):
    sign = 1 if row.option_type == "C" else -1
    return (
        row.open_interest
        * row.gamma
        * 100
        * spot_price
        * spot_price
        * 0.01
        * sign
    )
```

---

### Step 8 — Aggregate by Strike

```python
strike_gex = (
    option_gex_df
    .groupby(["strike", "option_type"])
    ["gex"]
    .sum()
    .unstack(fill_value=0)
)
```

Normalize columns:

```python
call_gex = C
put_gex = P
net_gex = call_gex + put_gex
abs_gex = abs(call_gex) + abs(put_gex)
```

---

### Step 9 — Identify Key Levels

Compute:

```python
call_wall = strike with max(call_gex)
put_wall = strike with min(put_gex)
max_abs_gamma = strike with max(abs_gex)
net_gamma_wall = strike with max(abs(net_gex))
```

Optional:

```python
nearest_large_positive_gex_above_spot
nearest_large_negative_gex_below_spot
```

---

### Step 10 — Estimate Gamma Regime

```python
total_gex = strike_gex["net_gex"].sum()
```

Rule of thumb:

```text
total_gex > 0 → more pinning / mean-reversion bias
total_gex < 0 → more expansion / momentum bias
```

This should be treated as a regime descriptor, not a trade signal by itself.

---

## 10. Visualization

### 10.1 Main Chart

Bar chart:

- x-axis: strike
- y-axis: net GEX
- vertical line: current SPX spot
- optional labels:
  - call wall
  - put wall
  - max gamma strike

### 10.2 Suggested Chart Filters

Show only strikes within a configurable range around spot:

```python
lower = spot_price - 300
upper = spot_price + 300
```

For 0DTE, too wide a strike range adds visual noise.

### 10.3 Optional Separate Charts

- Call GEX by strike
- Put GEX by strike
- Absolute GEX by strike
- Net GEX by strike

---

## 11. Output Report

Each snapshot should produce:

```text
SPX 0DTE GEX Snapshot
Timestamp
Spot price
Total net GEX
Call wall
Put wall
Largest absolute gamma strike
Nearest gamma concentration above spot
Nearest gamma concentration below spot
Regime interpretation
```

Example:

```text
SPX 0DTE GEX Snapshot — 2026-05-09 09:25 ET

Spot: 5,225

Total Net GEX: Positive
Regime: Pinning / mean-reversion bias

Call Wall: 5,250
Put Wall: 5,200
Largest Absolute Gamma: 5,225

Interpretation:
Spot is between major gamma concentrations at 5,200 and 5,250.
Expect these levels to act as important intraday reference zones.
```

---

## 12. Suggested Project Structure

```text
spx-gex-snapshot/
├── pyproject.toml
├── README.md
├── .env.example
├── src/
│   └── spx_gex/
│       ├── __init__.py
│       ├── config.py
│       ├── tasty_client.py
│       ├── chain.py
│       ├── greeks.py
│       ├── snapshot.py
│       ├── gex.py
│       ├── levels.py
│       ├── plot.py
│       └── report.py
├── notebooks/
│   └── exploratory_snapshot.ipynb
├── output/
│   ├── charts/
│   └── snapshots/
└── tests/
    ├── test_gex_formula.py
    ├── test_levels.py
    └── test_snapshot_pipeline.py
```

---

## 13. Module Responsibilities

### `config.py`

- credentials
- symbol settings
- strike window
- snapshot time
- output paths

### `tasty_client.py`

- session creation
- API wrappers
- streamer helpers if needed

### `chain.py`

- fetch option chain
- normalize symbols
- filter 0DTE

### `greeks.py`

- fetch / stream gamma
- validate gamma completeness

### `snapshot.py`

- orchestrate full snapshot
- join chain, OI, gamma, spot

### `gex.py`

- compute option-level GEX
- aggregate strike-level GEX

### `levels.py`

- identify call wall
- put wall
- max gamma
- nearest levels around spot

### `plot.py`

- generate matplotlib charts

### `report.py`

- generate markdown summary

---

## 14. MVP Implementation Plan

### Milestone 1 — Data Pull

Deliverable:

- authenticate
- fetch option chain
- produce normalized 0DTE dataframe

Success criteria:

```text
Can list all same-day SPX/SPXW strikes with call/put metadata.
```

---

### Milestone 2 — Metrics Join

Deliverable:

- attach open interest
- attach gamma
- attach spot price

Success criteria:

```text
At least 95% of relevant near-spot contracts have OI and gamma.
```

---

### Milestone 3 — GEX Calculation

Deliverable:

- compute option-level GEX
- aggregate by strike

Success criteria:

```text
Output dataframe contains strike, call_gex, put_gex, net_gex, abs_gex.
```

---

### Milestone 4 — Chart

Deliverable:

- save PNG chart of net GEX by strike
- include spot line

Success criteria:

```text
Chart is readable and filtered to relevant strikes around spot.
```

---

### Milestone 5 — Markdown Report

Deliverable:

- generate daily markdown summary

Success criteria:

```text
Report includes spot, total GEX, walls, and interpretation.
```

---

### Milestone 6 — Scheduling

Deliverable:

- run snapshot at configurable time
- optional rerun every 30 minutes

Success criteria:

```text
Snapshot runs unattended and writes timestamped output.
```

---

## 15. Validation Plan

### 15.1 Unit Tests

Test:

- call sign is positive
- put sign is negative
- zero OI produces zero GEX
- missing gamma excluded
- aggregation sums correctly

### 15.2 Sanity Checks

Before trusting output:

- spot sits inside visible strike range
- OI values are nonzero near ATM
- gamma peaks near ATM for 0DTE
- largest GEX values occur near high-OI strikes
- chart does not show obvious symbol-join failures

### 15.3 Manual Comparison

Compare against one external GEX chart for several days.

Do not expect exact match.

Validate:

- major levels roughly align
- regime classification broadly aligns
- call / put walls are plausible

---

## 16. Known Limitations

This model does not know true dealer positioning.

It assumes:

```text
calls are positive
puts are negative
```

It does not account for:

- intraday opening / closing flow
- true buyer / seller initiation
- dealer inventory
- spread trades
- block trade classification
- same-day OI changes

Therefore, label output as:

```text
OI-based SPX 0DTE GEX snapshot
```

Not:

```text
true dealer GEX
```

---

## 17. Future Enhancements

### 17.1 Periodic Refresh

Run every:

- 30 minutes
- 15 minutes
- 5 minutes near open / close

Uses updated gamma and spot, but still stale OI.

### 17.2 Multi-Expiry Snapshot

Compare:

- 0DTE only
- 1DTE
- weekly expiry
- all expiries

### 17.3 Gamma Flip Estimate

Compute net GEX across hypothetical spot levels.

For each hypothetical spot:

```python
recompute gamma or approximate using current gamma
sum net GEX
find zero crossing
```

More accurate version requires recomputing gamma at each spot.

### 17.4 OPRA Flow Layer

Only after the snapshot model proves useful:

- ingest full trade tape
- classify trade flow
- update estimated dealer inventory intraday
- compare flow-adjusted GEX vs OI-based GEX

---

## 18. Recommended First Build

Start with the simplest reliable version:

```text
One script.
One snapshot.
One chart.
One markdown report.
```

Recommended command:

```bash
uv run spx-gex-snapshot --symbol SPX --expiry today --window 300
```

Output:

```text
output/
├── charts/
│   └── spx_0dte_gex_YYYYMMDD_0925.png
└── snapshots/
    └── spx_0dte_gex_YYYYMMDD_0925.md
```

---

## 19. Trading Use

Use the snapshot to frame the day:

- Where is spot relative to major gamma strikes?
- Is total GEX positive or negative?
- Are there clear walls above or below?
- Is the market likely to pin, mean-revert, or expand?

Do not use GEX alone as a trade trigger.

Combine with:

- price action
- opening range
- VWAP
- MACD / HMA / RSI if used in the existing trading process
- scheduled news events

---

## 20. Final Summary

The start-of-day GEX snapshot is the right first version.

It provides useful SPX market structure without solving the harder OPRA / intraday-flow problem.

The model is:

```text
Tastytrade option chain
+ open interest
+ gamma
+ spot
= OI-based SPX 0DTE GEX snapshot
```

This should be built before attempting any real-time dealer-flow model.
