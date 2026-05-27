# TT-139 GEX Backend — Evaluation Summary (2026-05-26)

## Verdict
The per-strike GEX engine is **implemented correctly** and **methodology-matched** to the
documented industry standard (chartgex / SpotGamma), and it ran clean against **live RTH
ticks** all morning with **zero errors and zero autonomous fixes required**.

## 1. Methodology validation (vs chartgex / standard)
| Element | Standard | Ours | Match |
|---|---|---|---|
| Formula | Γ × OI × contractsize × Spot² × 0.01 | OI × γ × M × spot² × 0.01 | ✅ |
| Sign | calls +, puts − | +1 call / −1 put | ✅ |
| Net | Σ call − Σ put | call_gex + put_gex | ✅ |
| Scaling | per 1% move (×0.01) | GEX_SCALE = 0.01 | ✅ |
| Underlying scaling | Spot² (not strike²) | spot**2 all rows | ✅ |
| Exposure source | Open Interest | open_interest | ✅ |
| Gamma | broker/IV gamma, positive both legs | broker gamma, sign via option_type | ✅ |

## 2. Static + functional gates
- 26 GEX unit tests; full analytics subtree 286 passed.
- ruff, pyright (strict), mypy — all clean.
- Functional ACs (live REST): spot-in-range, ±10% window, gamma-peak-near-ATM, cache TTL+HIT — all PASS.

## 3. Live RTH tracking — 2026-05-26, 9:30–12:00 ET (6 fires, SPX/SPY/AAPL)
Every fire healthy; spots advanced each interval; walls re-centered with price; no errors; no code changes.

SPX intraday: spot 7516 → 7527 → 7534 → 7532 → 7516 → 7507 (rallied at open, faded into noon).
Call wall tracked 7500↔7550 with spot; put wall held a stable 7490 floor all morning.

## 4. Plots (.gex-rth/plots/)
- `spx_gex_aggregate_all-expiries.png` — conventional GEX profile (29 expiries): call wall ~7600, put walls 7400 & round-number 7000. Matches the chartgex-style shape.
- `spx_gex_0dte_single-expiry.png` — single 0DTE: gamma spike at ATM (expected on expiry day).
- `spx_intraday_walls.png` — capstone: spot vs call/put walls across the morning.

## 5. Follow-ups filed (not defects)
- Surface total net GEX / regime flag (positive vs negative) — stated v1 goal not yet exposed.
- Cross-expiration aggregate-by-strike profile as a first-class function.
- Gamma-flip / zero-gamma level (BS gamma across hypothetical spot; uses IV we already capture).

## Data / logs
`.gex-rth-2026-05-26.jsonl` (raw captures) · `.gex-rth/notes.md` (per-run agent verdicts) ·
`.gex-rth/run.{cron,agent}.log`. Implemented on branch `feature/TT-139-gex-backend-data-collection` (PR #181).
