# TT-138: GEX Snapshot — Implementation Plan

> **Jira:** [TT-138](https://mandeng.atlassian.net/browse/TT-138)
> **Branch:** `feature/TT-138-spx-0dte-gex-snapshot` *(retained; v1 validation target is SPX 0DTE)*
> **Design spec:** [docs/requirements/TT-138-gex-snapshot-spec.md](../requirements/TT-138-gex-snapshot-spec.md) *(treated as immutable point-in-time design; this plan is authoritative for current direction — see §6.12)*
> **Status:** Round 1 review complete. Resolved decisions inlined below; deferred questions remain in §6.

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

## 6. Open Questions — Round 1 Status

Each subsection is tagged with one of:

- **RESOLVED** — decision made; inlined into the plan.
- **DEFERRED** — gated by another open question; revisit when that one resolves.
- **OPEN** — still needs a decision.

### 6.1 — Batch size — RESOLVED (single-expiry assumption)

**Decision:** the snapshot assumes a **single expiration per invocation**. Multi-expiry comparisons are achieved by multiple invocations, not by widening one fetch.

**Implication:** SPX 0DTE single-expiry chain is ~282 strikes × 2 = 564 OCC symbols ≈ 16KB query string. Likely fits in one REST call. URL-cap concerns are essentially eliminated by this assumption; chunking only kicks in if a single chain exceeds the empirical cap (to be measured during implementation, not gated on it).

**Open sub-decision:** within the single expiry, do we still pre-filter strikes (e.g., drop zero-OI far-OTM strikes) before the fetch, or fetch all strikes and filter post-fetch? Default is **fetch all strikes** unless empirical batch size proves problematic.

### 6.2 — Liveness of REST values during market hours — RESOLVED

**Decision: (a)** — re-probe at market open during RTH and verify `updated-at` advances continuously. Result determines whether REST is sufficient or whether we need to revisit the architecture.

**Action item:** rerun `scripts/probe_rest_endpoints.py` Monday near 09:35 ET. Capture two snapshots ~60s apart and confirm `updated-at` for both spot and a near-ATM option advance.

### 6.3 — Refresh cadence — DEFERRED

Gated on §6.2. If REST values are continuously fresh during RTH, periodic refresh is nearly free and (b)/(c) become attractive. If REST values lag, (a) may be the only sensible mode regardless.

Revisit after §6.2 probe.

### 6.4 — Module placement — DEFERRED

Gated on §6.8. If visualization (a) — right-axis overlay on `tasty-chart` — wins, then placement (b) "extend `charting/`" is the natural choice. If a standalone artifact wins, placement (a) "new `analytics/gex/`" is cleaner.

Revisit after §6.8 mockups exist.

### 6.5 — CLI entry point — OPEN (not yet reviewed)

Original options stand:

- (a) New entry point `tasty-gex` in `pyproject.toml`.
- (b) Subcommand on `tasty-chart` (e.g. `tasty-chart gex --symbol SPX`).
- (c) Subcommand on `tasty-signal`.

### 6.6 — Output artifacts — OPEN (not yet reviewed)

Original options stand:

- (a) Static PNG + markdown per snapshot, written to `output/` (matches spec §11).
- (b) Live web view (HTML/SVG over HTTP).
- (c) Both.

### 6.7 — Persistence — RESOLVED (with day-2 note)

**Decision (v1):** Redis snapshot only — write the latest aggregated strike-level GEX (per-symbol, per-expiration) to a Redis HSET keyed `tastytrade:latest:GEXSnapshot` (or similar), and publish on a Redis pub/sub channel for downstream consumers.

**Day-2 follow-up (NOT in v1):** also persist GEX-by-strike rows to InfluxDB for historical replay across days/weeks. This will be tracked as a separate ticket once v1 is shipped.

Implementation impact: `render.py` (or a new `publisher.py`) emits a publish + HSET write at the tail of each snapshot. No InfluxDB schema work in v1.

### 6.8 — Visualization design — RESOLVED (next step: mock all three)

**Decision:** mock up all three viz candidates before picking one. Decision deferred until mockups can be compared visually.

Three candidates to mock:

- (a) **Right-axis overlay on tasty-chart** — net GEX bars overlaid on intraday candles via right axis.
- (b) **Standalone bar chart (spec §10.1)** — vertical bars of net GEX by strike with spot vline + wall labels.
- (c) **Horizontal lollipop split** — strikes on y-axis; `call_gex` right, `put_gex` left.

Multi-expiration view (small-multiples vs overlay) will be addressed inside each mockup.

**Action item:** create three interactive HTML mockups under `.plan-review/mockups/TT-138-gex-viz-{a,b,c}.html` using sample SPX 0DTE data so the comparison is concrete.

### 6.9 — Strike window for display — DEFERRED

Gated on §6.8. Window semantics differ across viz styles (e.g., right-axis overlay uses spot-relative window for visual alignment with candles; standalone bar chart can auto-fit to non-zero GEX strikes). Pick the window approach once the viz is picked.

Note this is also the same parameter as §6.1's "relevant strike window for the fetch" — they should converge on a single concept.

### 6.10 — Default expirations for the CLI — DEFERRED

Reviewer to research what standard convention calls for in published GEX tools (SpotGamma, MenthorQ, etc). Revisit after that read.

### 6.11 — Spec doc rename — RESOLVED (applied)

**Decision: (a)** — renamed to `docs/requirements/TT-138-gex-snapshot-spec.md` via `git mv` (history preserved). Plan-doc references updated.

### 6.12 — Spec erratum for §6 step 6 — RESOLVED

**Decision: (b)** — leave the spec immutable as a point-in-time design artifact. Plans evolve; the spec records the original reasoning and should not be rewritten retroactively. This plan is authoritative for current design direction.

### 6.13 — Futures-options probe — OPEN

Decision pending between:

- (a) Run a futures-options REST probe as part of v1.
- (b) Spawn a separate exploration ticket later.

Either way, futures-options *implementation* is out of v1 scope.

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
