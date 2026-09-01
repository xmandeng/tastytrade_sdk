# Condor Overlay Study — Complementary Premium Against TT-156 Loss Days

**Date:** 2026-08-31 · **Verdict: falsified — do not build.** Standalone study;
deliberately kept out of [TT156_RESEARCH_LOG.md](TT156_RESEARCH_LOG.md) so the
living log tracks only the strategy actually being run.

## The question

The kalman-primary butterfly loses on chop days — repeated flip-exit
scratches, no completions (20 of 51 traded days, −$7,257 total in the
54-session ledger). Chop days are exactly when short premium collects. Can a
same-day SPX iron condor, sold at 10:00 ET alongside the fly, cushion those
days without eating the tent days?

## Data & method

- **Chain evidence:** the 54 recorded sessions (2026-06-11 → 2026-08-31),
  priced from the actual 10:00 ET chain snapshot at mid, held to recorded
  settlement, canonical all-in costs (0.10 slippage + measured fees per
  spread, $5/ITM leg). Joint book = condor daily P&L + `w25_5m_m0_kal_ef5`
  daily all-in.
- **History evidence:** SPX 5m candles Jan 2025 → Aug 2026 (423 trading
  days): |10:00 → close| move per day. No chains exist before Jun 2026, so
  historical condors can't be priced — the history disciplines *breach
  frequency*, the chains price the *premium*.
- **Structures:** short call + put verticals, 25-pt wings, short strikes at
  (a) fixed distance D ∈ {25, 50, 75}, or (b) k × the 10:00 ATM-straddle
  expected move (EM), k ∈ {1.0 … 3.0}. Gates tested: net day-start GEX ≥ 0;
  chop-trigger (enter only after the day's 2nd kalman flip before noon).

Solo baseline over the same 54 days: kal early-fly **$24,121**, Sharpe 6.7,
maxDD −$1,455.

## Result 1 — fixed-distance condors (54 chain days)

| Config | Overlay | Cushion on loss days | Drag on win days | Joint Sharpe | Joint maxDD |
|---|---|---|---|---|---|
| ±25, w25/w50 | +$3.2–8.2k | **−$3.7 to −$4.8k (hurts)** | −$5.0–6.0k | 5.3–5.5 | −$7.5 to −$10.4k |
| ±50, w50 | +$7.4k | +$1.7k | $0 | 7.0 | −$3.9k |
| ±75, w25 | +$3.4k | +$1.5k | ~$0 | **7.4** | **−$1,109** |
| ±75, w50 | +$4.8k | +$2.4k | $0 | 7.6 | −$1,111 |

- **"Chop" still travels ±25 points.** Tight condors lose on the very days
  they were meant to cushion — the intuitive version is falsified first.
- GEX gating and chop-triggering both made things worse (fewer trades, kept
  the losses, or degraded drawdown). Rejected.
- ±75/w25 looked ideal in-sample: paid on 15/20 loss days, ~$0 collision
  with the fly, drawdown *better* than solo.

## Result 2 — the 423-day history kills fixed distance

| Jan 2025 → Aug 2026 (423 days) | Value |
|---|---|
| Days finishing inside ±75 of the 10:00 price | 384/423 = **90.8%** (90.3% '25, 91.2% '26) |
| Breach days | 39 (~1.8/month): 19 partial, 20 past the wing (−$2,413 each) |
| Move distribution | median 16 / p90 70 / p99 144 / max 223 pts (Apr 2025) |
| 423-day total at today's ~$87 credit | **−$38,416 (−$91/day)** |

The 54-day window contained one breach where the base rate says five — the
in-sample +$3.4k was a quiet-regime artifact. Twenty full-cap breaches swamp
384 days of dimes. (Caveat: credits would be higher on high-vol days, but
that cannot be verified without historical chains.)

## Result 3 — expected-move scaling is regime-safe but earns dimes

Strikes at k × EM (10:00 ATM straddle; median EM 28 pts this window):

| k | Overlay | Avg win | Breaches | Cushion | Drag | Joint Sharpe | Joint maxDD |
|---|---|---|---|---|---|---|---|
| 1.0 | +$3,349 | $501 | 14 | −$3,524 | −$4,471 | 5.5 | −$5,936 |
| 1.25 | +$4,464 | $348 | 10 | −$942 | −$2,148 | 6.4 | −$3,652 |
| 1.5 | +$4,751 | $253 | 6 | +$974 | −$1,190 | 7.0 | −$3,192 |
| 2.0 | +$2,628 | $114 | 2 | +$1,782 | $0 | 6.9 | −$3,332 |
| 2.5 | +$1,140 | $52 | 1 | +$881 | $0 | 6.9 | −$2,390 |
| 3.0 | +$733 | $22 | 1 | +$344 | $0 | 6.9 | −$1,518 |

Breach-discipline over the 423 days (EM proxied by an EWMA of realized
|move|, calibrated 1.05:1 against the real straddles on the 51 overlap
days): k=1.5 breaches 27.8% of all days and **26.7% inside the Mar–May 2025
crash window — regime-flat by construction**. Scaling works exactly as
intended: implied vol widens the strikes in step with danger.

**And that is precisely why it earns nothing.** Constant k×EM ⇒ constant
breach probability ⇒ the only income is the volatility risk premium at that
strike — $20–50/day at safe distances, against an occasional −$2,400 tail.
Every k underperforms fixed-75 in-sample (worse Sharpe, worse drawdown at
every multiple, including k≈2.7-equivalent widths). Fixed-75's in-sample
outperformance came from selling *relatively closer strikes on higher-vol
days* — i.e., from taking exactly the uncompensated regime risk that the
423-day history prices at −$91/day.

## Why the idea fails structurally

The two designs fail from opposite ends and there is no middle:

- **Fixed distance** = a short-vol regime bet. Pays in quiet regimes,
  destroyed in vol regimes (April 2025: breaches cluster at ~1/3 of days at
  pennies of stored credit).
- **EM-scaled** = regime-neutral tail harvesting. Survives every regime but
  the compensated edge at collision-free distances is ~$20–90/day — thin,
  margin-hungry ($2.2k+/day), and one tail event erases months.

The butterfly's loss days are the cost of holding its right tail (in-tent
settlements). Selling far tails to cushion them doesn't remove that cost —
it relocates it to a worse-priced tail.

## Decision

No condor arm is built or tracked. This is the fifth independent
falsification of the same family of instinct — after stops, defer-to-fade,
bank-on-fade, and credit-trailing — and it fails for the same root reason:
**selling premium to smooth this strategy sells a tail that is worth more
than the premium received.**

The search for a complement continues; what this study rules out is the
short-premium family specifically. A true complement must pay on chop days
without being short a tail — i.e., defined-debit structures that are *long*
the pin, not short the move.
