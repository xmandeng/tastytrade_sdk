# TT-138: GEX Snapshot — Implementation Plan

> **Jira:** [TT-138](https://mandeng.atlassian.net/browse/TT-138)
> **Branch:** `feature/TT-138-spx-0dte-gex-snapshot` *(retained; v1 validation target is SPX 0DTE)*
> **Design spec:** [docs/requirements/spx_0dte_gex_snapshot_design_spec.md](../requirements/spx_0dte_gex_snapshot_design_spec.md)
> **Status:** Draft — open questions in §6 must be resolved before implementation begins.

---

## 1. Summary

Build a point-in-time **Gamma Exposure (GEX) snapshot** for any underlying with a Tastytrade option chain. The snapshot identifies gamma concentration zones (call wall, put wall, max-gamma strike) and broad regime (positive vs negative net GEX) using only the Tastytrade REST API.

**v1 validation target:** SPX 0DTE — common starting point because of high liquidity, narrow chain, and well-known external GEX references for sanity comparison.

**The tool is symbol- and expiration-agnostic from day one.** The architecture accepts:

- Any underlying with a Tastytrade option chain (indexes like SPX, ETFs like SPY, equities like AAPL)
- Any expiration date (0DTE, weekly, monthly, LEAP)
- One or many expirations in a single snapshot

**Futures-options support is unverified.** Only `equity-option=` has been probed. The same REST mechanism likely applies to `future-option=` but field availability (Greeks, OI) needs probing — see §6.13. Futures options are out of v1 scope until that probe runs.

**Not in v1:** OPRA tape, Time & Sales, dealer-position inference, DXLink streaming, order execution, backtesting, futures options.

---

## 2. Architecture (verified by live REST probe — equity options only)

The data surface is **three REST calls** for equity-option-style chains (verified):

1. `GET /option-chains/<symbol>/nested` — strikes + OCC symbols + streamer symbols
2. `GET /market-data/by-type?<spot-key>=<symbol>` — spot price (`spot-key` is `index` for SPX, `equity` for AAPL/SPY)
3. `GET /market-data/by-type?equity-option=<batch>` — gamma + OI + IV + mark per option (batched)

Then: per-option GEX, group by strike, identify levels, render.

```
Auth → Chain fetch → Filter expirations → Spot fetch
                              ↓
            Batched market-data fetch (Greeks + OI per option)
                              ↓
            Compute per-option GEX → Aggregate by strike (per expiry)
                              ↓
            Identify levels → Render chart + markdown
```

**No async websocket lifecycle. No subscription cap. No snapshot-completion semantics. No dependency on `tasty-subscribe` running.**

The `<spot-key>` branching is handled by a small mapping (`SPX → index`, ETF/equity → `equity`). Adding futures-options later means adding a `<symbol-prefix> → futures` branch and a separate `future-option=` market-data path **after the futures-options probe in §6.13 confirms the field surface**.

---

## 3. Why this differs from the original spec

The original spec (§6 step 6) treated DXLink Greeks as the preferred gamma source and Black-Scholes as fallback.

The probe at `scripts/probe_rest_endpoints.py` confirmed that `/market-data/by-type?equity-option=...` returns **all Greeks plus open-interest plus theo-price plus IV** in a single call. Sample (live, 2026-05-09):

```
"volatility":   "0.206242718"
"delta":        "-0.005448905"
"gamma":        "0.000113572"
"theta":        "-0.34742129"
"vega":         "0.104008626"
"theo-price":   "0.239992046"
"open-interest": 168
```

This eliminates: DXLink subscription cap concerns, snapshot-completion semantics, async websocket lifecycle, dependency on a running streamer service, and the Black-Scholes fallback. The spec needs an erratum noting REST is the source — see §6.12.

**Caveat: only equity-options probed.** The same REST endpoint accepts a `future-option=` parameter, but whether the response includes Greeks + OI for futures options is **unverified**. See §6.13.

---

## 4. Module Structure (proposed — see §6.4)

Tentative new package `src/tastytrade/analytics/gex/`:

| File | Responsibility |
|---|---|
| `client.py` | REST batch fetchers (chain, market-data, spot); chunking; symbol-class dispatch (index vs equity) |
| `compute.py` | per-option GEX formula + strike-level aggregation |
| `levels.py` | call wall, put wall, max-gamma, net-gamma-wall |
| `render.py` | chart + markdown emitters |
| `cli.py` | entry point |

The package name `gex` is symbol-agnostic — no `spx_` or `0dte_` in the module hierarchy.

---

## 5. Implementation Steps

5.1 — Add `OptionMarketDataClient` for batched `/market-data/by-type?equity-option=...` (handles chunking per the cap decision in §6.1).

5.2 — `fetch_chain_for_expirations(symbol, expirations) -> pl.DataFrame` returning strikes + OCC symbols filtered to one or more expirations (reuses existing `tastytrade.market.option_chains`).

5.3 — `fetch_option_market_data(occ_symbols) -> pl.DataFrame` chunked → DataFrame of `gamma`, `open_interest`, `mark`, `volatility` per option.

5.4 — `fetch_spot(symbol) -> float` — dispatches on symbol class (`index` for SPX, `equity` for SPY/AAPL/etc).

5.5 — `compute_option_gex(df, spot) -> pl.DataFrame` and `aggregate_by_strike(df) -> pl.DataFrame` with columns `strike, expiration, call_gex, put_gex, net_gex, abs_gex`. Aggregates by `(expiration, strike)` so multi-expiry snapshots are first-class.

5.6 — `identify_levels(strike_df, spot) -> Levels` per expiration: `call_wall`, `put_wall`, `max_abs_gamma`, `net_gamma_wall`, optional `nearest_above_spot`, `nearest_below_spot`.

5.7 — `render_chart(strike_df, levels, spot) -> Path` (PNG or HTML — see §6.6) and `render_markdown(strike_df, levels, spot) -> Path`.

5.8 — Wire CLI entry point per §6.5; CLI must accept `--symbol` and `--expiry` (one or many).

5.9 — Unit tests: formula sign, zero OI → zero GEX, missing gamma exclusion, aggregation correctness, level identification.

5.10 — Live REST sanity: SPX 0DTE first, then re-run for SPY weekly + AAPL monthly to prove generality across equity-option targets.

---

## 6. Open Questions

Each item is an independent decision. Resolve before starting implementation.

### 6.1 — Batch size for `equity-option=` query parameter

SPXW today has ~282 strikes × 2 = 564 OCC symbols × ~28 chars/sym ≈ 16KB query string. AAPL or SPY weekly chains can run several thousand contracts across all strikes. The endpoint's actual cap is unknown.

- (a) Empirical probe: test with 50, 100, 200, 500 symbols; find the break point.
- (b) Pick a conservative batch (e.g., 50) and skip the test.
- (c) Read latest chain size and dynamically chunk.

### 6.2 — Liveness of REST values during market hours

Saturday probe returned EOD values from Friday's close. Need confirmation that values update continuously during RTH.

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

For multi-expiration view: small-multiples (one chart per expiry) vs overlay (color-coded expiries on one chart).

### 6.9 — Strike window for display

Spec §10.2 suggests spot ± 300. That value is SPX-scale; for SPY-scale (~$500) ±300 is far too wide.

- (a) Hardcoded scalar — insufficient across symbols.
- (b) Configurable via CLI flag (`--window 300`).
- (c) Auto-fit to non-zero GEX strikes (symbol-agnostic).
- (d) Configurable as a percentage of spot (e.g., ±5%) — symbol-agnostic and predictable.

### 6.10 — Default expirations for the CLI

The architecture supports any number of expirations. The question is what the CLI defaults to.

- (a) Today's expiration only (matches the spec's "0DTE snapshot" framing).
- (b) Today + next expiration.
- (c) All expirations within N days (e.g., next 7 days).
- (d) No default — `--expiry` is required.

### 6.11 — Spec doc rename

Original spec is at `docs/requirements/spx_0dte_gex_snapshot_design_spec.md` — its name reflects the original SPX 0DTE framing.

- (a) Rename to `docs/requirements/TT-138-gex-snapshot-spec.md` (matches the generalized plan-doc).
- (b) Leave alone — preserves the historical design framing.

### 6.12 — Spec erratum for §6 step 6

The original spec lists DXLink Greeks as preferred. The REST probe proved that's no longer the right design.

- (a) Edit the spec in place to point to REST as the gamma/OI source.
- (b) Leave the spec immutable as a design-history artifact; let the plan be authoritative.

### 6.13 — Futures-options support

**Currently unverified.** We have only probed `equity-option=`. The REST endpoint accepts `future-option=` for symbols like `/MESU5EX3M5 250620C6450`, but whether the response includes Greeks + OI is unknown. Futures-options also differ from equity-options in:

- Symbol format (`/MESU5EX3M5 250620C6450` vs `SPXW  260511C07055000`)
- Multiplier per product (varies by future; not always 100)
- Settlement style and exercise mechanics
- Chain endpoint (`/futures-option-chains/:symbol/nested`, not `/option-chains/...`)

The futures-options exploration is an independent work item. **Decision needed:**

- (a) Run a short futures-options REST probe as part of v1 (extend `scripts/probe_rest_endpoints.py` to also walk `/MES`, `/ES`, or similar). Defer the actual code-level support to a follow-up ticket regardless.
- (b) Skip the probe in v1 entirely; spawn a separate exploration ticket later.

Even if (a) confirms full field availability, futures-options *implementation* is still out of v1 scope per §1 — only the probe is in scope here.

---

## 7. Validation Plan

### 7.1 Unit tests

- call sign positive
- put sign negative
- zero OI → zero GEX
- missing gamma excluded
- aggregation sums correctly per (expiration, strike)
- level identification on synthetic data

### 7.2 Live REST sanity (per spec §15.2)

Run during RTH against multiple equity-option targets to prove generality:

- **SPX 0DTE** (primary v1 validation): spot inside visible strike range; OI nonzero near ATM; gamma peaks near ATM; largest GEX at high-OI strikes.
- **SPY weekly** (ETF generalization check): same checks, scaled to SPY strikes.
- **AAPL monthly** (equity generalization check): same checks, smaller chain.

### 7.3 Manual external comparison (per spec §15.3)

Compare SPX output against one external GEX chart for several days. Validate:

- major levels roughly align
- regime classification broadly aligns
- call / put walls are plausible

Exact match is not expected.

### 7.4 Futures-options probe (if §6.13 = a)

Extend `scripts/probe_rest_endpoints.py` to walk `/futures-option-chains/<root>/nested` and `/market-data/by-type?future-option=<batch>` for one liquid futures product (e.g. `/MES`). Capture the full response shape. Document field availability (Greeks present? OI present? same names?) in a follow-up note. **Does not gate v1 implementation.**

---

## 8. References

- **Probe script:** `scripts/probe_rest_endpoints.py` (equity-options only; futures-options walk pending §6.13)
- **Existing chart skeleton:** `src/tastytrade/charting/server.py`
- **Chain fetcher:** `src/tastytrade/market/option_chains.py`
- **Greeks model (DXLink, not used in v1):** `src/tastytrade/messaging/models/events.py:85`
