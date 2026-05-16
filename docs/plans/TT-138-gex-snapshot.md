# TT-138: GEX Snapshot — Implementation Plan

> **Jira:** [TT-138](https://mandeng.atlassian.net/browse/TT-138)
> **Branch:** `feature/TT-138-spx-0dte-gex-snapshot` *(retained; v1 validation target is SPX 0DTE)*
> **Design spec:** [docs/requirements/TT-138-gex-snapshot-spec.md](../requirements/TT-138-gex-snapshot-spec.md) *(treated as immutable point-in-time design; this plan is authoritative for current direction — see §6.12)*
> **Status:** Round 2 review complete. §6.13 futures-options probe completed; findings inlined.

---

## 1. Summary

Build a point-in-time **Gamma Exposure (GEX) snapshot** for any underlying with a Tastytrade option chain. The snapshot identifies gamma concentration zones (call wall, put wall, max-gamma strike) and broad regime (positive vs negative net GEX) using only the Tastytrade REST API.

**v1 validation target:** SPX 0DTE — common starting point because of high liquidity, narrow chain, and well-known external GEX references for sanity comparison.

**The tool is symbol- and expiration-agnostic from day one.** The architecture accepts:

- Any underlying with a Tastytrade option chain (indexes like SPX, ETFs like SPY, equities like AAPL)
- Any expiration date (0DTE, weekly, monthly, LEAP)
- One or many expirations in a single snapshot

**Futures-options REST surface is now verified.** Probed `/MES` and `/ES` (see §6.13); `future-option=` returns the same field set as `equity-option=` (gamma, delta, theta, vega, rho, volatility, theo-price, open-interest). Implementation of futures-options in the GEX tool is still **out of v1 scope** — five implementation differences documented in §6.13.

**Not in v1:** OPRA tape, Time & Sales, dealer-position inference, DXLink streaming, order execution, backtesting, futures-options *implementation*.

---

## 2. Architecture (verified by live REST probe — equity-options is the v1 surface)

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

The `<spot-key>` branching is handled by a small mapping (`SPX → index`, ETF/equity → `equity`). Adding futures-options later is a separate pathway with its own chain endpoint, symbol encoding, and multiplier rules — see §6.13. Same Greeks + OI surface, but **not** a drop-in extension of the equity-options client.

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

## 4. Module Structure (proposed — see §6.4)

Tentative new package `src/tastytrade/analytics/gex/`:

| File | Responsibility |
|---|---|
| `client.py` | REST batch fetchers (chain, market-data, spot); chunking; symbol-class dispatch (index vs equity) |
| `compute.py` | per-option GEX formula + strike-level aggregation |
| `levels.py` | call wall, put wall, max-gamma, net-gamma-wall |
| `render.py` | chart + markdown emitters |
| `cli.py` | entry point |

The package name `gex` is symbol-agnostic — no `spx_` or `0dte_` in the module hierarchy. Futures-options support, when added, slots into `client.py` as a parallel dispatch path keyed on the leading `/` of the underlying.

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

## 6. Open Questions — Status

### 6.0 — Roll-up (read this first)

#### Resolved — no further action

| § | Decision |
|---|---|
| 6.1 | Single-expiry per invocation |
| 6.6 | (b) Live web view (HTML/SVG over HTTP) |
| 6.7 | Redis snapshot v1; InfluxDB persistence day-2 |
| 6.8 | Mock all three viz candidates before picking — three mockups built; mockup (d) hybrid is the picked direction |
| 6.11 | Spec doc renamed via `git mv` (applied) |
| 6.12 | Spec left immutable (point-in-time artifact) |
| 6.13 | Futures-options REST surface probed; field availability identical to equity-options. Implementation deferred to a post-v1 ticket; five differences vs equity-options recorded in §6.13. |

#### Prerequisites — must complete before any code starts

| § | What | Owner |
|---|---|---|
| 6.2 | Liveness experiment — rerun `scripts/probe_rest_endpoints.py` during RTH and confirm `updated-at` advances continuously | **Blocker for TT-139** |

#### Cascade decisions — resolved automatically after prerequisites

| § | Resolves once… |
|---|---|
| 6.3 | §6.2 liveness experiment captures evidence |
| 6.4 | Mockup (d) hybrid is the picked viz → biases toward extending `charting/`; reviewer to confirm |

#### Deferred to TT-139 (backend sub-task) — owner decides during implementation

- **§6.1 sub-decision** — pre-filter strikes vs fetch all (default: fetch all)

#### Deferred to TT-140 (frontend sub-task) — owner decides during implementation

- **§6.5** — CLI entry point (new `tasty-gex` vs subcommand on `tasty-chart` or `tasty-signal`)
- **§6.9** — Strike window for display (hardcoded vs configurable vs auto-fit vs percentage of spot)
- **§6.10** — Default expirations for the CLI (today only vs today+next vs window vs required flag)

### Ready to proceed?

**Yes**, subject to one critical-path sequence:

1. Run the §6.2 liveness experiment (one short session during RTH).
2. Confirm §6.4 module placement (mockup d picks the direction).
3. TT-139 implements backend (handles its own §6.1 sub-decision).
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

### 6.2 — Liveness of REST values during market hours — OPEN — experiment required

**Not yet decided.** This is a TODO, not a design decision. The Saturday probe returned EOD values; whether REST values update continuously during RTH is unverified.

**Experiment to run:** rerun `scripts/probe_rest_endpoints.py` near 09:35 ET on a trading day. Capture two snapshots ~60s apart and confirm `updated-at` advances for both SPX spot and at least one near-ATM SPXW option. Capture gamma and OI deltas between the two snapshots.

**Outcomes that branch the design:**

- ✅ Values advance continuously → REST is sufficient; proceed with the architecture in §2.
- ❌ Values stale or lag noticeably → architecture must be revisited; DXLink streaming may be required after all. **Stop and replan.**

This experiment gates §6.3 (cadence) and any TT-139 implementation work.

### 6.3 — Refresh cadence — OPEN (pending §6.2 experiment)

**Not yet decided.** Cannot be settled until the §6.2 liveness experiment runs.

If REST values are continuously fresh during RTH, periodic refresh is nearly free and a long-running snapshot loop (b) or a CLI-plus-orchestrator pair (c) become attractive. If REST values lag, one-shot CLI (a) may be the only sensible mode regardless of preference.

**Action:** revisit after §6.2 probe captures evidence.

### 6.4 — Module placement — DEFERRED (mockup d picks the direction)

Mockup (d) — hybrid right-anchored lollipop overlay on the candle chart — is the picked viz direction. That biases placement toward **(b) extend `charting/`**: the lollipop overlay layers onto the existing `src/tastytrade/charting/server.py` candle-rendering pattern.

Reviewer to confirm (b) explicitly before TT-139 begins, since the file layout depends on this choice.

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

Context for TT-140: window semantics differ across viz styles. For mockup (d) right-anchored lollipops, a spot-relative window (e.g., ±5% of spot) is the natural fit. This is also the same parameter as §6.1's "relevant strike window for the fetch" — they should converge on a single concept.

### 6.10 — Default expirations for the CLI — DEFERRED to TT-140

CLI defaults belong with the frontend sub-task. Decision moved to TT-140.

Context for TT-140: reviewer to research what standard convention calls for in published GEX tools (SpotGamma, MenthorQ, etc) before picking a default.

### 6.13 — Futures-options probe — RESOLVED

**Probed 2026-05-16 against `/MES` and `/ES`. REST surface is identical to equity-options.** Both products return gamma, delta, theta, vega, rho, volatility, theo-price, dx-mark, open-interest, plus standard quote fields via `GET /market-data/by-type?future-option=<sym>`. Decision: (a) — probe completed; *implementation* of futures-options in the GEX tool remains out of v1, but the pathway is now clear and recorded.

Probe scripts in `scripts/`:

- `probe_futures_options.py` — chain walk + field-availability check (run first)
- `probe_futures_options_metadata.py` — symbol-format, multiplier-source, and instrument-endpoint follow-up

#### Five implementation differences vs equity-options (post-v1 work)

1. **Chain endpoint shape** — `GET /futures-option-chains/<root>/nested` returns `data.option-chains[].expirations[].strikes[]`. Note the wrapper key is `option-chains` (NOT `futures-option-chains`).
2. **URL path needs slash-stripping** — root comes back as `/MES`; the URL is `/futures-option-chains/MES/nested`. Same applies anywhere the root goes into a path component.
3. **Symbol format is opaque, do not parse it** — examples: `./MESM6X3AK6 260518C7690` (1 space) vs `./ESM6 E3AK6 260518C5400` (2 spaces). The leading `.` flags a futures-option. The chain endpoint already breaks out `underlying-symbol` (the future), `option-contract-symbol` (the option series like `X3AK6`), `expiration-date`, `strike-price`, and the full `call` / `put` OCC strings. Use those structurally; pass the OCC string opaquely to `?future-option=...`. aiohttp URL-encodes it automatically for query params; for path components (e.g. `/instruments/future-options/<sym>`) you must call `urllib.parse.quote(sym, safe='')` explicitly.
4. **Multiplier is on the *underlying future*, not the option** — equity-options use `100` (shares per contract). Futures-options need the per-product `notional-multiplier` (equivalently `contract-size`) from `GET /instruments/futures/<future_symbol>` — e.g., 5.0 for /MES, 50.0 for /ES. The option-instrument endpoint's `multiplier` field is 1.0 (a different concept — one option = one futures contract). The chain expiration's `notional-value` and `display-factor` are also *not* the GEX multiplier (0.05 and 0.01 respectively for /MES; not dollar-per-point). GEX formula becomes:
   ```
   gex = OI × gamma × notional_multiplier × spot² × 0.01 × sign
   ```
   where `notional_multiplier` is fetched per-product (5 for /MES, 50 for /ES, etc.) and `spot` is the *future's* price (from a Quote on the future symbol, or `GET /market-data/by-type?future=<sym>`).
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
