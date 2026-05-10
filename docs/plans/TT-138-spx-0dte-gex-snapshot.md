# TT-138: SPX 0DTE GEX Snapshot — Implementation Plan

> **Jira:** [TT-138](https://mandeng.atlassian.net/browse/TT-138)
> **Branch:** `feature/TT-138-spx-0dte-gex-snapshot`
> **Design spec:** [docs/requirements/spx_0dte_gex_snapshot_design_spec.md](../requirements/spx_0dte_gex_snapshot_design_spec.md)
> **Status:** Draft — open questions in §6 must be resolved before implementation begins.

---

## 1. Summary

Build a point-in-time SPX 0DTE Gamma Exposure (GEX) snapshot using only the Tastytrade REST API. The snapshot identifies gamma concentration zones (call wall, put wall, max-gamma strike) and broad regime (positive vs negative net GEX) to frame intraday SPX market structure.

**Not in v1:** OPRA tape, Time & Sales, dealer-position inference, DXLink streaming, order execution, backtesting.

---

## 2. Architecture (verified by live probe)

The full data surface is **three REST calls**:

1. `GET /option-chains/SPX/nested` → strikes + OCC symbols + streamer symbols
2. `GET /market-data/by-type?index=SPX` → spot price
3. `GET /market-data/by-type?equity-option=<batch>` → gamma + OI + IV + mark per option (batched)

Then: per-option GEX, group by strike, identify levels, render.

```
Auth → Chain fetch → Filter to expiry → Spot fetch
                                ↓
            Batched market-data fetch (Greeks + OI per option)
                                ↓
            Compute per-option GEX → Aggregate by strike
                                ↓
            Identify levels → Render chart + markdown
```

No async websocket lifecycle. No subscription cap. No snapshot-completion semantics. No dependency on `tasty-subscribe` running.

---

## 3. Why this differs from the original spec

The original spec (§6 step 6) treated DXLink Greeks as the preferred gamma source and Black-Scholes as fallback. The probe at `scripts/probe_rest_endpoints.py` confirmed that `/market-data/by-type?equity-option=...` returns **all Greeks plus open-interest plus theo-price plus IV** in a single call. Sample response (live, captured 2026-05-09):

```
"volatility":   "0.206242718"
"delta":        "-0.005448905"
"gamma":        "0.000113572"
"theta":        "-0.34742129"
"vega":         "0.104008626"
"theo-price":   "0.239992046"
"open-interest": 168
```

This eliminates: DXLink subscription cap concerns, snapshot-completion semantics, async websocket lifecycle, dependency on a running streamer service, and the Black-Scholes fallback. The spec needs an erratum noting REST is the source.

---

## 4. Module Structure (proposed — see open question §6.4)

Tentative new package `src/tastytrade/analytics/gex/`:

| file | responsibility |
|---|---|
| `client.py` | REST batch fetchers (chain, market-data); chunking |
| `compute.py` | per-option GEX formula + strike-level aggregation |
| `levels.py` | call wall, put wall, max-gamma, net-gamma-wall |
| `render.py` | chart + markdown emitters |
| `cli.py` | entry point |

---

## 5. Implementation Steps

5.1 — Add `OptionMarketDataClient` for batched `/market-data/by-type?equity-option=...` (handles chunking per the cap decision in §6.1).

5.2 — `fetch_chain_for_expiry(symbol, expiry) -> pl.DataFrame` returning strikes + OCC symbols (reuses existing `tastytrade.market.option_chains`).

5.3 — `fetch_option_market_data(occ_symbols) -> pl.DataFrame` chunked → DataFrame of `gamma`, `open_interest`, `mark`, `volatility` per option.

5.4 — `fetch_index_spot(symbol) -> float`.

5.5 — `compute_option_gex(df, spot) -> pl.DataFrame` and `aggregate_by_strike(df) -> pl.DataFrame` with columns `strike, call_gex, put_gex, net_gex, abs_gex`.

5.6 — `identify_levels(strike_df, spot) -> Levels` dataclass: `call_wall`, `put_wall`, `max_abs_gamma`, `net_gamma_wall`, optional `nearest_above_spot`, `nearest_below_spot`.

5.7 — `render_chart(strike_df, levels, spot) -> Path` (PNG or HTML — see §6.6) and `render_markdown(strike_df, levels, spot) -> Path`.

5.8 — Wire CLI entry point per §6.5.

5.9 — Unit tests: formula sign, zero OI → zero GEX, missing gamma exclusion, aggregation correctness, level identification on synthetic data.

5.10 — Live REST sanity verification (see §7).

---

## 6. Open Questions

Each item is an independent decision. Resolve before starting implementation.

### 6.1 — Batch size for `equity-option=` query parameter

Today's SPXW chain has ~282 strikes × 2 = 564 OCC symbols × ~28 chars/sym ≈ 16KB query string. The endpoint's actual cap is unknown.

- (a) Empirical probe: test with 50, 100, 200, 500 symbols; find the break point.
- (b) Pick a conservative batch (e.g., 50) and skip the test.
- (c) Read latest chain size and dynamically chunk.

### 6.2 — Liveness of REST values during market hours

Saturday probe returned EOD values from Friday's close. Need confirmation that values update continuously during RTH (the docs claim no delayed quotes via REST for funded accounts).

- (a) Re-probe at market open Monday and verify `updated-at` advances continuously.
- (b) Treat as verified-during-implementation; code defensively against stale `updated-at`.

### 6.3 — Refresh cadence

Spec §17.1 lists periodic refresh as future. With REST, periodic refresh is nearly free.

- (a) Pure one-shot CLI: invoke when wanted, write artifact, exit.
- (b) Long-running snapshot loop with configurable interval (15/30 min).
- (c) Both: CLI for one-shot, separate orchestrator for periodic.

### 6.4 — Module placement

- (a) New package `src/tastytrade/analytics/gex/` (sibling to `analytics/positions.py`).
- (b) Extend `charting/` (reuse server skeleton; add `/gex` route).
- (c) Standalone `src/tastytrade/gex/` top-level.

### 6.5 — CLI entry point

- (a) New entry point `tasty-gex` in `pyproject.toml`.
- (b) Subcommand on `tasty-chart` (e.g. `tasty-chart gex --symbol SPX`).
- (c) Subcommand on `tasty-signal`.

### 6.6 — Output artifacts

- (a) Static PNG + markdown per snapshot, written to `output/` (matches spec §11).
- (b) Live web view (HTML/SVG over HTTP).
- (c) Both.

### 6.7 — Persistence

Per project rule: live → Redis pub/sub, historical → InfluxDB.

- (a) No persistence — snapshot is ephemeral, output files only.
- (b) Write GEX-by-strike rows to InfluxDB for historical replay.
- (c) Publish via Redis pub/sub for downstream consumers.

### 6.8 — Visualization design

Three candidates:

- (a) **Right-axis overlay on tasty-chart** — net GEX bars overlaid on intraday candles via right axis; maximum reuse of `lightweight-charts` frontend.
- (b) **Standalone bar chart (spec §10.1)** — vertical bars of net GEX by strike with spot vline + wall labels.
- (c) **Horizontal lollipop split** — strikes on y-axis; call_gex right, put_gex left.

Mockups should be drawn before code.

### 6.9 — Strike window for display

Spec §10.2 suggests spot ± 300.

- (a) Hardcode spot ± 300.
- (b) Configurable via CLI flag (`--window 300`).
- (c) Auto-fit to non-zero GEX strikes.

### 6.10 — Multi-expiration support

Spec §3 suggests optional 0DTE + next expiration comparison.

- (a) v1 = today only, simplest.
- (b) v1 = today + next expiration side-by-side.

### 6.11 — Spec doc rename

Original spec is at `docs/requirements/spx_0dte_gex_snapshot_design_spec.md`. User asked to rename "accordingly."

- (a) Rename to `docs/requirements/TT-138-spx-0dte-gex-snapshot-spec.md` (matches plan-doc convention).
- (b) Leave the spec name alone; only the plan gets the TT-138 prefix.

### 6.12 — Spec erratum for §6 step 6

The original spec lists DXLink Greeks as preferred. The REST probe proved that's no longer the right design.

- (a) Edit the spec in place to point to REST as the gamma/OI source.
- (b) Leave the spec immutable as a design-history artifact; let the plan be authoritative.

---

## 7. Validation Plan

### 7.1 Unit tests

- call sign positive
- put sign negative
- zero OI → zero GEX
- missing gamma excluded
- aggregation sums correctly per strike
- level identification on synthetic strike data

### 7.2 Live REST sanity (per spec §15.2)

Run against live chain during RTH and verify:

- spot inside visible strike range
- OI nonzero at near-ATM strikes
- gamma peaks near ATM for 0DTE
- largest GEX values occur at high-OI strikes

### 7.3 Manual external comparison (per spec §15.3)

Compare against one external GEX chart (e.g. SpotGamma, MenthorQ) for several days. Validate:

- major levels roughly align
- regime classification broadly aligns
- call / put walls are plausible

Exact match is not expected (different conventions, different feeds).

---

## 8. References

- **Probe script:** `scripts/probe_rest_endpoints.py`
- **Existing chart skeleton:** `src/tastytrade/charting/server.py` (pattern reference, not necessarily reused)
- **Chain fetcher:** `src/tastytrade/market/option_chains.py`
- **Greeks model (DXLink):** `src/tastytrade/messaging/models/events.py:85` (NOT used in v1; kept for reference if a flow-adjusted GEX layer is added later per spec §17.4)
