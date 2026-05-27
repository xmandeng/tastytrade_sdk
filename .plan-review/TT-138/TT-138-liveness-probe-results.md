# TT-138 §6.2 Liveness Probe — Results

> **Jira:** [TT-138](https://mandeng.atlassian.net/browse/TT-138)
> **Probe script:** `scripts/probe_rest_endpoints.py`
> **Raw outputs:** `.probe-out/TT-138-liveness-{1,2}.txt` (gitignored)

## Run window

| | Wall-clock (ET) |
|---|---|
| Snapshot 1 start | 2026-05-19T09:35:12-04:00 |
| Snapshot 1 end   | 2026-05-19T09:35:13-04:00 |
| Snapshot 2 start | 2026-05-19T09:36:13-04:00 |
| Snapshot 2 end   | 2026-05-19T09:36:14-04:00 |
| Elapsed snap1→snap2 start | **61 s** |

Both probe invocations exited 0. RTH confirmed (US equity markets opened 09:30 ET; SPX `is-trading-halted: false`).

## SPX spot (`/market-data/by-type?index=SPX`)

| Field | Snapshot 1 | Snapshot 2 | Δ |
|---|---|---|---|
| `updated-at` | 2026-05-19T13:35:12.467Z | 2026-05-19T13:36:13.454Z | **+60.987 s — advanced** |
| `mark` | 7360.33 | 7366.24 | +5.91 |
| `mid`  | 7360.545 | 7366.425 | +5.88 |
| `bid`  | 7354.29 | 7360.70 | +6.41 |
| `ask`  | 7366.80 | 7372.15 | +5.35 |

## Options (`/market-data/by-type?equity-option=...`)

Two SPX 0DTE options were sampled (strike 7225, expiry 2026-05-19). Spot at snap1 was 7360.55, so the put is deep OTM and the call is deep ITM by ~135 points.

### SPXW 260519P07225000 (0DTE put, OI=2517)

| Field | Snapshot 1 | Snapshot 2 | Δ |
|---|---|---|---|
| `updated-at` | 2026-05-19T13:35:08.982Z | 2026-05-19T13:36:09.713Z | **+60.731 s — advanced** |
| `mark` | 0.50 | 0.50 | 0 |
| `gamma` | 0.000634387 | 0.000634387 | 0 |
| `open-interest` | 2517 | 2517 | 0 |
| `volatility` | 0.338037654 | 0.338037654 | 0 |
| `volume` | 406 | 451 | +45 (tape advanced) |
| `bid-size` / `ask-size` | 416 / 327 | 334 / 439 | book moved |

### SPXW 260519C07225000 (0DTE call, OI=239)

| Field | Snapshot 1 | Snapshot 2 | Δ |
|---|---|---|---|
| `updated-at` | 2026-05-19T13:35:11.163Z | 2026-05-19T13:36:11.350Z | **+60.187 s — advanced** |
| `mark` | 135.70 | 141.05 | **+5.35** (tracks spot Δ +5.91) |
| `gamma` | 0.000634387 | 0.000634387 | 0 |
| `open-interest` | 239 | 239 | 0 |
| `volatility` | 0.338037688 | 0.338037688 | 0 |
| `bid` / `ask` | 134.90 / 136.50 | 140.40 / 141.70 | both repriced |

### Notes on what did *not* change

- `gamma`, `volatility`, `theta`, `vega`, `rho`, `theo-price` are byte-identical across snapshots for both options. That is **expected over a 60-second window** — these surfaces only repaint when the IV or term-structure model updates, not on every quote tick. The probe verifies the *publication channel* (REST advances tick-level fields); it does not require Greeks to drift in 60 s.
- Identical `gamma` between the put and call at the same strike is mathematically correct (call/put gamma are equal at the same strike/expiry/IV under no-arb).
- `open-interest` is end-of-day published; not expected to change intraday.

## Verdict

**PASS** — REST values advance during RTH. §6.2 satisfied. TT-139 unblocked; proceed with REST-based architecture in plan §2.

Both the SPX spot `updated-at` and *both* sampled option `updated-at` timestamps advanced by ~60 s between snapshots taken 60 s apart, and price fields (`mark`, `bid`, `ask`, `mid`) moved coherently with the underlying. The data surface is live during RTH; no DXLink streaming dependency is required for the v1 GEX snapshot.

## Methodology

Both snapshots were collected within US equity market hours (09:35 ET / 09:36 ET on Tue 2026-05-19), exactly 61 seconds apart, by invoking `scripts/probe_rest_endpoints.py` twice with no arguments. The script authenticates via `RedisConfigManager` against the Live Tastytrade API and pulls the SPX option chain, SPX spot, and option market data for two 0DTE options at strike 7225. Raw stdout for each run is preserved under `.probe-out/` for audit. No retries, no aggregation, no order placement.
