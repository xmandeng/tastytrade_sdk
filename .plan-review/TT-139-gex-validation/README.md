# TT-139 GEX Backend — Validation Materials

> **Jira:** [TT-139](https://mandeng.atlassian.net/browse/TT-139) — GEX Snapshot: backend data collection and computation
> **Parent Story:** [TT-138](https://mandeng.atlassian.net/browse/TT-138) · **Epic:** [TT-96](https://mandeng.atlassian.net/browse/TT-96)
> **Follow-ups:** [TT-151](https://mandeng.atlassian.net/browse/TT-151) (net-GEX / regime) · [TT-152](https://mandeng.atlassian.net/browse/TT-152) (cross-expiration aggregate function) · [TT-153](https://mandeng.atlassian.net/browse/TT-153) (gamma-flip / zero-gamma)

Live-data validation of the TT-139 GEX backend (`src/tastytrade/analytics/gex/`),
SPX/SPY/AAPL, 2026-05-26. Confirms the implementation is correct and methodology-matched
to the industry standard (chartgex / SpotGamma / insiderfinance).

## Contents
- **`EVALUATION.md`** — methodology validation table, static/functional gates, the full morning RTH result.
- **`plots/`** — rendered GEX charts:
  - `TT-139-gex-review.png` — combined 3-panel review.
  - `spx_gex_aggregate_all-expiries.png` — aggregate GEX profile (chartgex-style).
  - `spx_gex_insiderfinance-style.png` — aggregate profile with summary box (spot / walls / net-GEX / regime).
  - `spx_gex_0dte_single-expiry.png` — single 0DTE expiry (gamma spike at ATM).
  - `spx_intraday_walls.png` — live RTH spot vs call/put walls across the morning.
- **`data/`** — evidence: `agent-verdicts.md` (per-run autonomous-vetting verdicts) and `captures-2026-05-26.jsonl` (raw snapshots).
- *(The plots/data were produced by one-off `/tmp` harnesses against the live Tastytrade REST API + the `gex` package — not committed, as they are not lint-clean product code. The methodology is fully documented in `EVALUATION.md`.)*

## Result (see EVALUATION.md for detail)
- Methodology matches the standard formula exactly: `GEX = OI × γ × M × spot² × 0.01`, calls +, puts −, per-1% scaling, open interest, broker-provided gamma.
- Static + functional gates all green (26 GEX unit tests; 286 analytics; ruff / pyright-strict / mypy).
- 6 live RTH fires (9:30–12:00 ET) all healthy: spots advanced each interval, walls re-centered with price, zero errors, zero code changes required.

> Note: the `zero-γ` (gamma flip) line is intentionally absent — it requires a Black-Scholes
> gamma re-evaluation across hypothetical spot and is tracked as TT-153. Everything else in the
> chartgex/insiderfinance profile is produced by the current backend.
