# TT-156 Research Log — 0DTE SPX Butterfly

Living document. The **Current strategy** section always reflects the rule the
collector runs today; the **Findings log** is append-only, newest first. Update
both whenever the rule changes, and record the evidence that forced the change.

Data home: `research_data/TT-156/` (per-day `events.jsonl` ledger,
`SCOREBOARD.md` running totals). Ticket: TT-156.

## Current strategy (as of 2026-08-28)

- **Signal (primary):** constant-velocity Kalman filter on sealed 5m SPX
  closes, q/r = 0.025 (`KALMAN_Q_OVER_R`). The velocity sign is the tangent;
  a sign flip on a sealed bar is the signal. No intra-candle action
  (`confirm_on_close`).
- **Entries:** on a kalman flip inside 10:00–13:00 ET, sell the ATM vertical
  in the flip direction (bull put spread on up-flip, bear call spread on
  down-flip). First 30 min is churn; 13:00+ entries lack time to complete.
- **Exits (either-flip):** close an incomplete vertical on the FIRST flip from
  *either* family — kalman or hull. The hull flip is a deliberate kill-switch
  backstop for errant/wrong-direction spreads. No stop-loss, ever: every stop
  level tested made results worse; the flip exit is the stop.
- **Completion:** when total credit ≥ width, buy the counter vertical —
  lossless iron fly; hold tents to 16:00 settlement. Forced close of
  incomplete verticals at 15:45.
- **Primary arms:** `w25_5m_m0_kal` (25-wide), `w50_5m_m0_kal` (50-wide),
  `w25_5m_m0_kal_ef5` (early-fly: at 5 pts adverse, buy the counter side now —
  bounded deficit, tent kept). These drive the charts, strategy table, and
  running totals.
- **Tracked controls:** the hull arms (`w25_5m_m0`, `w25_5m_m1`,
  `w25_5m_m0_ef5`, `w50_5m_m0`) stay in the grid as the lagging control.
- **Cost model (all-in):** mid fills − 0.075 concession − 0.05 fees per spread
  order − $5 per ITM leg at settlement.
- **MACD:** not a control anywhere. Post-hoc report label only
  (agree/converge/diverge at entry).

## Findings log

### 2026-08-28 — Kalman tangent adopted as primary; either-exit backstop; width economics

**Kalman beats hull on a plateau, not a point.** 53-session resim on recorded
chains, identical trade rule, all-in costs. Sweep of the one q/r knob:

| q/r | 25-wide | 25-wide early-fly | 50-wide | trades |
|---|---|---|---|---|
| hull (control) | $7,016 | $7,062 | $5,543 | 190 |
| 0.01 | $6,207 | $7,174 | $5,696 | 158 |
| 0.015 | $13,228 | $14,907 | $11,546 | 175 |
| 0.02 | $19,954 | $22,572 | $16,190 | 181 |
| **0.025** | **$21,016** | **$24,560** | **$15,523** | 202 |
| 0.03 | $17,788 | $23,076 | $12,660 | 210 |
| 0.05 | $14,472 | $17,297 | $14,283 | 236 |
| 0.10 | $7,744 | $10,032 | $4,323 | 295 |

Every setting 0.015–0.05 beats the hull 2–3x. Mechanism (visible in trade
counts): the winning band trades the hull's own flip set with better timing —
faster settings manufacture trades, slower ones revert to hull lag. Frozen at
0.025 (best measured point, consensus of curve fits across arms). A
single-setting win would have been discarded as luck; the plateau is the
evidence.

**Either-exit backstop is free insurance.** Exits on whichever family flips
first. The hull backstop bound on 12 distinct flips in 53 sessions and was
*additive* on every arm — the hull occasionally seals a profit the kalman
would have given back (worst bind -$240; typical binds +$400–800):

| Arm | pure kalman exit | either-exit (adopted) |
|---|---|---|
| 25-wide | $21,016 | $21,298 |
| 25-wide early-fly | $24,560 | $24,843 |
| 50-wide | $15,523 | $15,968 |

**Width is a fixed-cost amortization problem.** Same rule at narrow widths
(early-fly trigger scaled to 20% of width): w5 loses -$470 even with
early-fly; w10 makes $5,908 — rescued by kalman timing but far below w25's
$24,843 on ~40% of the margin. Friction is flat per spread order (~$12.50,
~$50 per completed fly) regardless of width: a couple percent of a 25-wide
credit, the whole edge of a 5-wide. Costs don't scale with risk; w25 is the
sweet spot. Same practical-sweet-spot shape as the q/r tuning — a ridge
between two failure modes (fee-domination vs completion-starvation;
noise-chasing vs lag).

**Early-fly is robust across signals.** The overlay added within *every*
signal config tested (hull, fast/medium/smooth kalman) and its edge grows as
the signal gets twitchier — it converts whipsaw damage into deficit tents.

**Operational.** History restated as the kalman-primary ledger (running
totals through 2026-08-28: 25-wide $21,298, 50-wide $15,968). Prior
hull-primary ledger backed up at
`research_data/TT-156/ledger_backups/hull_primary_20260828/`. Commits:
ec32950, 18cf5d4, 0a509e4. Forward test live from 2026-08-31. Also verified:
the July disk rescue was complete — Influx holds SPX 1m candles back to Jan
2025 (irreplaceable; dxlink's 1m lookback is only months). The backtest bound
is chain snapshots (recording began 2026-06-11), not candles.

### 2026-08-27/28 — Clean slate: hull-only rule after feed-lag contamination

TT-157: the candle pipeline had lagged minutes-to-hours for most of the
program (unbounded queue + per-event Influx writes), contaminating gate
stamps, entry timing, and regime reads; the live profits did not reproduce at
true signal timing. All MACD-based live controls were removed by user
directive ("direction always follows the hull — ignore the MACD"). Rebuilt
rule: hull-only 5m flips, entries 10:00–13:00, flip exits, no stop, complete
into flies, hold tents. History restated on clean candles. Fix: sealed-bar
Influx writes (TT-159, PR #187) + lag alarm (TT-157, PR #186). Companion
findings from the clean replay: 1m timeframe dead in every form (short and
long); afternoon entries net losers (window cut at 13:00); every stop-loss
level subtracts; prior-run stability filter hurts; early-fly conversion beats
any stop.

### Earlier milestones (pre-clean-slate, on contaminated feed — treat with care)

- **Bar-close gate** (`confirm_on_close`): engine acts only on sealed candles;
  eliminated intra-candle whipsaw entries.
- **First-entry calibration and flip-ETA gate**: superseded by the clean-slate
  rule; retained in code for replay tooling only.
- **Half-width credit arm** (24-variant grid, `_hw`): retired with the
  clean slate.
