# TT-138: GEX Snapshot — Implementation Plan

> **Jira:** [TT-138](https://mandeng.atlassian.net/browse/TT-138)
> **Branch:** `feature/TT-138-spx-0dte-gex-snapshot` *(retained; v1 validation target is SPX 0DTE)*
> **Design spec:** [docs/requirements/TT-138-gex-snapshot-spec.md](../requirements/TT-138-gex-snapshot-spec.md) *(treated as immutable point-in-time design; this plan is authoritative for current direction — see §6.12)*
> **Status:** Round 2 review complete. §6.13 futures-options probe completed; findings inlined. §6.2 RTH liveness probe **PASSED** 2026-05-19 — see [TT-138-liveness-probe-results.md](TT-138-liveness-probe-results.md). TT-139 unblocked.
> **Design locked 2026-05-25:** data-collection flow + runtime model finalized via design-review ([.design-review/TT-139-gex-backend-data-collection-design-review.html](../../.design-review/TT-139-gex-backend-data-collection-design-review.html)). §6.1 strike filter and §6.3 runtime model are now **RESOLVED** (see below).

---

## 1. Summary

Build a point-in-time **Gamma Exposure (GEX) snapshot** for any underlying with a Tastytrade option chain. The snapshot identifies gamma concentration zones (call wall, put wall, max-gamma strike) and broad regime (positive vs negative net GEX) using only the Tastytrade REST API.

**v1 validation target:** SPX 0DTE — common starting point because of high liquidity, narrow chain, and well-known external GEX references for sanity comparison.

**The tool is symbol- and expiration-agnostic from day one.** The architecture accepts:

- Any underlying with a Tastytrade option chain (indexes like SPX, ETFs like SPY, equities like AAPL)
- Any expiration date (0DTE, weekly, monthly, LEAP)
- One or many expirations in a single snapshot

**Hard rule: single-product per snapshot.** Each snapshot invocation binds to exactly one underlying instrument; metrics are rendered in that product's units. No cross-product overlays in v1. Comparing /MES vs /ES vs SPX requires running separate snapshots and is intentionally not a v1 feature — the pinning interpretation, axis units, and label semantics differ enough across products that mixing them would be misleading.

**Contract multiplier `M` is captured per product, never hard-coded.** Equity-options return `M=100`, futures-options return per-product values from `/instruments/futures/<sym>` (e.g., /MES=5, /ES=50, /NQ=20). The GEX formula reads `M` from the symbol context regardless of product class. This is what lets futures-options support land as a small extension rather than a parallel pipeline.

**Futures-options REST surface is verified.** Probed `/MES` and `/ES` (see §6.13); `future-option=` returns the same field set as `equity-option=` (gamma, delta, theta, vega, rho, volatility, theo-price, open-interest). Implementation of futures-options in the GEX tool is still **out of v1 scope** — five implementation differences documented in §6.13.

**Not in v1:** OPRA tape, Time & Sales, dealer-position inference, DXLink streaming, order execution, backtesting, futures-options *implementation*, cross-product overlays.

---

## 2. Architecture (verified by live REST probe — equity-options is the v1 surface)

The data surface is **four REST calls** for any single-product snapshot:

1. `GET /option-chains/<symbol>/nested` — strikes + OCC symbols + streamer symbols *(equity-options path; futures-options uses `/futures-option-chains/<root>/nested` — see §6.13)*
2. `GET /market-data/by-type?<spot-key>=<symbol>` — spot price for the snapshotted product (`index` for SPX, `equity` for SPY/AAPL, `future` for /ES/MES)
3. **Multiplier lookup** — `M=100` for equity-options (constant); for futures-options, `GET /instruments/futures/<future_sym>` returns `notional-multiplier`. Resolved once per snapshot, cached.
4. `GET /market-data/by-type?equity-option=<batch>` — gamma + OI + IV + mark per option (batched). Futures-options uses `?future-option=<batch>` with the same field shape.

Then: per-option GEX (using the looked-up `M`), group by strike, identify levels, render.

```
Auth → Resolve symbol context (spot-key, multiplier M, chain endpoint)
                              ↓
            Chain fetch → Filter expirations → Spot fetch
                              ↓
            Batched market-data fetch (Greeks + OI per option)
                              ↓
            Compute per-option GEX with M from context
                              ↓
            Aggregate by strike (per expiry)
                              ↓
            Identify levels → Render in snapshotted product's units
```

**No async websocket lifecycle. No subscription cap. No snapshot-completion semantics. No dependency on `tasty-subscribe` running.**

The symbol-context resolution (spot-key, multiplier, chain endpoint) is a single dispatch step keyed on the symbol class. `M` is just another value carried in the context — the formula site never knows the difference between equity-options and futures-options. This is what makes futures-options support a small extension (add the chain-endpoint and spot-key branches) rather than a parallel pipeline.

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

The `future-option=` parameter delivers the **same field set** for futures-options (verified 2026-05-16 against `/MES` and `/ES`). See §6.13 for the five implementation differences vs equity-options.

---

## 4. Module Structure — RESOLVED (§6.4)

New package `src/tastytrade/analytics/gex/` (TT-139 backend):

| File | Responsibility |
|---|---|
| `client.py` | REST batch fetchers (chain, market-data, spot, multiplier); chunking; **±10%-of-spot strike pre-filter** (§6.1); `resolve_symbol_context` (spot-key + M + chain endpoint per product class) |
| `compute.py` | per-option GEX formula + strike-level aggregation; **takes `M` as a parameter, never hard-codes 100** |
| `levels.py` | call wall, put wall, max-gamma, net-gamma-wall |
| `snapshot.py` | `take_snapshot(symbol, expirations)` request-handler/orchestrator: cache-check → client → compute → levels → publish envelope to Redis with TTL (runtime model A, §6.3) |

**Moved to TT-140 (frontend):** `render.py` (chart + markdown emitters, **always labelled in the snapshotted product's units**) and the CLI entry point (§6.5). They *consume* the snapshot envelope; they don't produce it, so they live with the frontend sub-task — not in `gex/`.

The package name `gex` is symbol-agnostic — no `spx_` or `0dte_` in the module hierarchy. Futures-options support, when added, plugs into `client.py`'s symbol-context resolver — the formula in `compute.py` is unchanged.

---

## 5. Implementation Steps

5.1 — Add `OptionMarketDataClient` for batched `/market-data/by-type?equity-option=...` (handles chunking per the cap decision in §6.1).

5.2 — `fetch_chain_for_expirations(symbol, expirations) -> pl.DataFrame` returning strikes + OCC symbols filtered to one or more expirations (reuses existing `tastytrade.market.option_chains`). Strikes are pre-filtered to **±10% of spot** — flat, no DTE-conditional logic (§6.1).

5.3 — `fetch_option_market_data(occ_symbols) -> pl.DataFrame` chunked → DataFrame of `gamma`, `open_interest`, `mark`, `volatility` per option.

5.4 — `resolve_symbol_context(symbol) -> SymbolContext` — returns a frozen dataclass containing `spot_key` (`index` / `equity` / `future`), `multiplier` (100 for equity-options; `notional-multiplier` from `/instruments/futures/<sym>` for futures-options), and `chain_endpoint` (path template for the chain fetch). One REST call per new symbol, cached. Both `fetch_spot(symbol)` and the chain fetcher consume this context.

5.5 — `compute_option_gex(df, spot, multiplier) -> pl.DataFrame` and `aggregate_by_strike(df) -> pl.DataFrame` with columns `strike, expiration, call_gex, put_gex, net_gex, abs_gex`. Formula: `gex = OI × γ × multiplier × spot² × 0.01 × sign`. The function takes `multiplier` as a parameter — **never** hard-codes 100. Aggregates by `(expiration, strike)` so multi-expiry snapshots are first-class.

5.6 — `identify_levels(strike_df, spot) -> Levels` per expiration: `call_wall`, `put_wall`, `max_abs_gamma`, `net_gamma_wall`, optional `nearest_above_spot`, `nearest_below_spot`.

5.7 — `take_snapshot(symbol, expirations) -> SnapshotEnvelope` orchestrator in `snapshot.py`: cache-check Redis `gex:snapshot:<sym>:<exp>`; on hit return the cached envelope (zero REST); on miss run client → compute → levels, write the envelope back with TTL ~60s, then return it. Runtime model A (§6.3).

5.8 *(TT-140)* — `render_chart` / `render_markdown` emitters and the CLI entry point (§6.5) move to the frontend sub-task. They consume the envelope produced by `take_snapshot` (via the HTTP response), and do not live in `gex/`.

5.9 — Unit tests: formula sign, zero OI → zero GEX, missing gamma exclusion, aggregation correctness, level identification.

5.10 — Live REST sanity: SPX 0DTE first, then re-run for SPY weekly + AAPL monthly to prove generality across equity-option targets.

---

## 6. Open Questions — Status

### 6.0 — Roll-up (read this first)

#### Resolved — no further action

| § | Decision |
|---|---|
| 6.1 | Single-expiry per invocation; **strike fetch pre-filtered to ±10% of spot** (flat, no DTE-conditional logic — locked 2026-05-25) |
| 6.6 | (b) Live web view (HTML/SVG over HTTP) |
| 6.7 | Redis snapshot v1; InfluxDB persistence day-2 |
| 6.8 | Mock all three viz candidates before picking — three mockups built; mockup (d) hybrid is the picked direction |
| 6.11 | Spec doc renamed via `git mv` (applied) |
| 6.12 | Spec left immutable (point-in-time artifact) |
| 6.13 | Futures-options REST surface probed; field availability identical to equity-options. Implementation deferred to a post-v1 ticket; five differences vs equity-options recorded in §6.13. |
| 6.2 | **PASS (2026-05-19 RTH probe).** Both SPX spot and 0DTE option `updated-at` advanced ~60s between two snapshots taken 60s apart; option mark tracked spot move. REST surface confirmed live during RTH. Evidence: [TT-138-liveness-probe-results.md](TT-138-liveness-probe-results.md). |
| 6.3 | **Runtime model A (on-demand, frontend-paced) — locked 2026-05-25.** Chart issues one request per refresh; backend serves from Redis cache `gex:snapshot:<sym>:<exp>` (TTL ~60s) on hit, else computes and caches. Chart consumes the **HTTP response**, not Redis — Redis is an internal recompute-skipping side-cache. Frontend owns refresh cadence + symbol switching; no backend timer/loop. |
| 6.4 | **Module placement split by sub-task.** TT-139 backend lives in (a) **new `src/tastytrade/analytics/gex/`** (analytics sibling, symbol-agnostic compute). TT-140 frontend extends `src/tastytrade/charting/` (the mockup (d) hybrid lollipop overlay layers onto the existing candle-rendering server). Both can coexist; the backend doesn't import the frontend. |

#### Prerequisites — must complete before any code starts

_All prerequisites met._ §6.2 probe ran 2026-05-19 09:35 ET and PASSED. TT-139 is unblocked.

#### Cascade decisions — remaining

_All cascade decisions resolved._ §6.4 settled 2026-05-20 (see Resolved table above).

#### Deferred to TT-139 (backend sub-task)

_Resolved 2026-05-25 via design-review._ §6.1 strike fetch = **±10% of spot, flat** (was "fetch all"); §6.3 runtime = **model A** (see Resolved table). No open backend sub-decisions remain.

#### Deferred to TT-140 (frontend sub-task) — owner decides during implementation

- **§6.5** — CLI entry point (new `tasty-gex` vs subcommand on `tasty-chart` or `tasty-signal`)
- **§6.9** — Strike window for display (hardcoded vs configurable vs auto-fit vs percentage of spot)
- **§6.10** — Default expirations for the CLI (today only vs today+next vs window vs required flag)

### Ready to proceed?

**Yes — TT-139 is unblocked as of 2026-05-19.** Remaining critical-path sequence:

1. ~~Run the §6.2 liveness experiment (one short session during RTH).~~ **DONE — PASS** ([results](TT-138-liveness-probe-results.md)).
2. Confirm §6.4 module placement (mockup d picks the direction → extend `charting/`).
3. **TT-139 implements backend** (§6.1 strike filter + §6.3 runtime model now locked — see design-review). ← _next_
4. TT-140 implements frontend (handles §6.5, §6.9, §6.10).
5. Futures-options *implementation* is post-v1; field-surface compatibility already verified.

### Per-subsection status legend

Each numbered subsection below is tagged with one of:

- **RESOLVED** — decision made; inlined into the plan.
- **DEFERRED** — gated by another open question in this plan; revisit when that one resolves.
- **DEFERRED to TT-139** — moved to the backend sub-task; will be decided there.
- **DEFERRED to TT-140** — moved to the frontend sub-task; will be decided there.
- **OPEN — experiment required** — outstanding TODO that needs empirical data before a design decision can be made.
- **OPEN** — still needs a decision.

### 6.2 — Liveness of REST values during market hours — RESOLVED (PASS)

**Decided 2026-05-19** via RTH probe (09:35 ET, Tue, trading day). Full results in [TT-138-liveness-probe-results.md](TT-138-liveness-probe-results.md).

Evidence summary:

- SPX spot `updated-at` advanced **+60.987 s** between two snapshots taken **61 s** apart; mark moved +$5.91 with the underlying.
- Both sampled SPX 0DTE options' `updated-at` advanced ~60 s; deep-ITM call's mark moved +$5.35 (tracking spot).
- Greeks (`gamma`, `theta`, `vega`, `volatility`) byte-identical over 60-s window — expected, as the IV surface only repaints on slower cadence. The probe verifies the *publication channel*, not Greek drift.

**Outcome:** ✅ Values advance continuously → REST is sufficient; architecture in §2 stands. No DXLink streaming dependency for v1.

### 6.3 — Runtime model — RESOLVED (model A: on-demand, frontend-paced)

**Locked 2026-05-25 via design-review** ([.design-review/TT-139-gex-backend-data-collection-design-review.html](../../.design-review/TT-139-gex-backend-data-collection-design-review.html)). §6.2 PASS established REST is continuously fresh during RTH, so refresh is nearly free; the remaining question was *who drives the refresh clock and where snapshot state lives*. GEX is the first **pull** data source in the codebase (every other live source — account-stream, subscribe — is **push** via DXLink), so something must decide when to re-fetch.

**Model A — on-demand, frontend-paced:**

- **Start chart:** chart issues one `request(symbol, expiry)`. `snapshot.py` checks Redis `gex:snapshot:<sym>:<exp>`; on a fresh hit it serves immediately (zero REST), on a miss it runs the pipeline, writes the envelope back with TTL ~60s, and returns it.
- **Session:** process-level singleton — authenticated once (lazily on first request), reused across all requests and all symbols, refreshed on token expiry. Never per-symbol.
- **Cache:** one Redis key per `(symbol, expiry)`, TTL ~60s (matches REST freshness). A fresh hit costs zero REST calls — two charts on the same symbol share the cached envelope. Symbol-context (spot-key, M, chain endpoint) is cached separately for the process lifetime: one lookup per new symbol.
- **Refresh:** the **frontend** is the clock — it re-requests every ~60s while open. Within TTL → cache hit (free); expired → recompute + rewrite. No backend timer/loop (consistent with the event-driven concurrency rule; the one timer is the frontend's, justified because REST has no push).
- **Change symbol:** chart requests the new symbol; the old `gex:snapshot:<sym>:*` key simply expires by TTL. No stop signal, no teardown.
- **Stop:** chart stops requesting; cache entries lapse on their own.

**Key boundary:** the chart consumes the **HTTP response** envelope, *not* Redis directly. Redis is the backend's internal recompute-skipping side-cache. (This is the distinction from the rejected model B, where Redis would have been the delivery channel and the chart would read from it — mirroring account-stream/subscribe. Model B was deferred as more infrastructure than v1 needs for a pull source.)

### 6.4 — Module placement — RESOLVED (split by sub-task)

**Decision (TT-139 backend):** **(a)** — new package `src/tastytrade/analytics/gex/`, sibling to `analytics/positions.py`. Symbol-agnostic compute lives here. Decided in TT-139 round-3 review (2026-05-20).

**Decision (TT-140 frontend):** extends `src/tastytrade/charting/`. Mockup (d) hybrid right-anchored lollipop overlay layers onto the existing `src/tastytrade/charting/server.py` candle-rendering pattern.

The two are compatible: backend computes and serves; under runtime model A (§6.3) the frontend consumes the **HTTP response** envelope (Redis is the backend's internal cache, not the frontend's read path). The backend has no import dependency on `charting/`.

### 6.5 — CLI entry point — DEFERRED to TT-140

CLI design belongs with the frontend sub-task. Decision moved to TT-140 (Frontend rendering and CLI).

Options preserved for context when TT-140 is worked:

- (a) New entry point `tasty-gex` in `pyproject.toml`.
- (b) Subcommand on `tasty-chart` (e.g. `tasty-chart gex --symbol SPX`).
- (c) Subcommand on `tasty-signal`.

### 6.8 — Visualization design — RESOLVED (mockup d is the picked direction)

Three mockups (a/b/c) plus the hybrid (d) were built at `.plan-review/mockups/TT-138-gex-viz-{a,b,c,d}.html`. Mockup (d) is the picked direction:

- **Candlestick fills the plot** — no side-by-side split; max reuse of `tasty-chart` patterns.
- **Right-anchored lollipops** — call (green) and put (red) GEX stems extend left from the right edge, anchored at ~98.5% paper-x.
- **Lollipop zone ~20% of plot width** — tightened from initial 34% per reviewer feedback.
- **Stems at 35% opacity, dot heads at 50% opacity** — candles remain readable underneath.
- **Split call/put only** — no net-GEX rendering mode in v1 (any netting is downstream/post-process per the TT-139 storage decision).

Multi-expiration view (small-multiples vs overlay) deferred until TT-140 implementation.

### 6.9 — Strike window for display — DEFERRED to TT-140

Display-window semantics belong with the frontend sub-task. Decision moved to TT-140.

Context for TT-140: window semantics differ across viz styles. For mockup (d) right-anchored lollipops, a spot-relative window is the natural fit. **The fetch window is now fixed at ±10% of spot (§6.1, locked 2026-05-25)** — so the display window is a sub-selection of what's already fetched and must be **≤ ±10%**. TT-140 picks the display default (e.g. ±5%) within that bound; it cannot show strikes the backend didn't fetch without widening §6.1.

### 6.10 — Default expirations for the CLI — DEFERRED to TT-140

CLI defaults belong with the frontend sub-task. Decision moved to TT-140.

Context for TT-140: reviewer to research what standard convention calls for in published GEX tools (SpotGamma, MenthorQ, etc) before picking a default.

### 6.13 — Futures-options probe — RESOLVED

**Probed 2026-05-16 against `/MES` and `/ES`. REST surface is identical to equity-options.** Both products return gamma, delta, theta, vega, rho, volatility, theo-price, dx-mark, open-interest, plus standard quote fields via `GET /market-data/by-type?future-option=<sym>`. Decision: (a) — probe completed; *implementation* of futures-options in the GEX tool remains out of v1, but the pathway is now clear and recorded.

Probe scripts in `scripts/`:

- `probe_futures_options.py` — chain walk + field-availability check (run first)
- `probe_futures_options_metadata.py` — symbol-format, multiplier-source, and instrument-endpoint follow-up

#### Five implementation differences vs equity-options (post-v1 work)

Note: §1's "M is captured per product" rule plus §2's `resolve_symbol_context` already absorb the multiplier and spot-key concerns into the v1 architecture. The remaining work to add futures-options is mainly the chain-endpoint and OCC-encoding plumbing.

1. **Chain endpoint shape** — `GET /futures-option-chains/<root>/nested` returns `data.option-chains[].expirations[].strikes[]`. Note the wrapper key is `option-chains` (NOT `futures-option-chains`).
2. **URL path needs slash-stripping** — root comes back as `/MES`; the URL is `/futures-option-chains/MES/nested`. Same applies anywhere the root goes into a path component.
3. **Symbol format is opaque, do not parse it** — examples: `./MESM6X3AK6 260518C7690` (1 space) vs `./ESM6 E3AK6 260518C5400` (2 spaces). The leading `.` flags a futures-option. The chain endpoint already breaks out `underlying-symbol` (the future), `option-contract-symbol` (the option series like `X3AK6`), `expiration-date`, `strike-price`, and the full `call` / `put` OCC strings. Use those structurally; pass the OCC string opaquely to `?future-option=...`. aiohttp URL-encodes it automatically for query params; for path components (e.g. `/instruments/future-options/<sym>`) you must call `urllib.parse.quote(sym, safe='')` explicitly.
4. **Multiplier source differs (already absorbed by §2 architecture)** — equity-options have `M=100` constant; futures-options pull `notional-multiplier` from `/instruments/futures/<future_symbol>` (e.g., 5.0 for /MES, 50.0 for /ES). Because v1 already routes M through `resolve_symbol_context`, the formula site is unchanged. *Side note: the option-instrument endpoint's `multiplier` field is 1.0 — a different concept (one option = one futures contract). Chain expiration's `notional-value` and `display-factor` are also not the GEX multiplier.*
5. **Instrument-metadata endpoint requires URL-encoded path** — `GET /instruments/future-options/<urllib.parse.quote(sym, safe='')>` works (returns `multiplier`, `notional-value`, `display-factor`, `option-type`, `strike-price`, `is-vanilla`, etc.). The raw-path variant 404s; the `?symbol=` query variant 403s. For the *underlying future*, `GET /instruments/futures/<future_symbol_without_leading_slash>` (e.g. `MESM6`) returns `contract-size`, `notional-multiplier`, `display-factor`, `tick-size`, `product-code`.

Field-availability summary (live 2026-05-16, EOD values):

| field | /MES | /ES |
|---|---|---|
| gamma | ✓ | ✓ |
| delta | ✓ | ✓ |
| theta / vega / rho | ✓ | ✓ |
| volatility | ✓ | ✓ |
| theo-price / dx-mark | ✓ | ✓ |
| open-interest | ✓ | ✓ |
| bid / ask / mark | ✓ | ✓ |

---

## 7. Validation Plan

### 7.1 Unit tests

- call sign positive
- put sign negative
- zero OI → zero GEX
- missing gamma excluded
- aggregation sums correctly per (expiration, strike)
- level identification on synthetic data
- **`compute_option_gex` takes `multiplier` as a parameter** — assert formula uses passed value, not a hard-coded 100. Parametrize with `multiplier ∈ {100, 50, 5}` and verify scales linearly
- **`resolve_symbol_context` returns correct multiplier per symbol class** — SPX/SPY/AAPL → 100; /MES → 5; /ES → 50 (mocked instruments-endpoint response)

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

### 7.4 Futures-options probe — DONE

Completed 2026-05-16 against `/MES` and `/ES`; see §6.13. Probe scripts retained under `scripts/probe_futures_options*.py`. No further validation is needed for v1; futures-options *implementation* will be its own ticket post-v1.

---

## 8. References

- **Probe script (equity-options):** `scripts/probe_rest_endpoints.py`
- **Probe script (futures-options field surface):** `scripts/probe_futures_options.py`
- **Probe script (futures-options symbol, multiplier, instrument-endpoint):** `scripts/probe_futures_options_metadata.py`
- **Viz mockups:** `.plan-review/mockups/TT-138-gex-viz-{a,b,c,d}.html`
- **Existing chart skeleton:** `src/tastytrade/charting/server.py`
- **Chain fetcher:** `src/tastytrade/market/option_chains.py`
- **Greeks model (DXLink, not used in v1):** `src/tastytrade/messaging/models/events.py:85`
