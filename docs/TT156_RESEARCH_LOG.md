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
  lossless iron fly; hold tents to settlement. Forced close of
  incomplete verticals at 15:45.
- **Settlement price (since 2026-09-04):** the official SPX close — the
  close of the SPX daily candle in InfluxDB for the session date, read at
  16:15 ET. Never a snapshot spot: the index keeps updating for ~4 minutes
  after 16:00. If the candle is missing the day stays unsettled; there is
  no approximation. The whole ledger was restated once on 2026-09-04 (see
  findings).
- **Primary arms:** `w25_5m_m0_kal` (25-wide), `w50_5m_m0_kal` (50-wide),
  `w25_5m_m0_kal_ef5` (early-fly: at 5 pts adverse, buy the counter side now —
  bounded deficit, tent kept). These drive the charts, strategy table, and
  running totals.
- **Tracked controls:** the hull arms (`w25_5m_m0`, `w25_5m_m1`,
  `w25_5m_m0_ef5`, `w50_5m_m0`) stay in the grid as the lagging control.
- **End-of-day fly — mandatory every session (decision 2026-09-03; arms
  added 2026-08-31):** a defined-debit long ATM 25-wide butterfly bought in
  the 14:00 ET window, held to settlement — long the afternoon pin, max
  loss = the debit. `pinfly25_all` is the primary and drives the chart
  card's EOD line. `pinfly25_notent` (only when no kalman tent exists yet)
  and `pinfly25_notent_mid` (no-tent + spot in the middle half of the
  day's range) stay in the grid as tracked alternatives. Evidence and the
  falsified short-premium alternatives:
  [TT156_CONDOR_OVERLAY_STUDY.md](TT156_CONDOR_OVERLAY_STUDY.md).
- **Cost model (all-in):** mid fills − 0.10 slippage buffer per spread order
  (user fills 0DTE at ~0.05; 0.10 guarantees the fill) − real fees measured
  on live 2026-08-26 fills ($3.44 per opening spread, $1.44 per closing
  spread — commission is charged on opens only; the CBOE index fee is the
  dominant component) − $5 per ITM leg at settlement.
- **MACD:** not a control anywhere. Post-hoc report label only
  (agree/converge/diverge at entry).

## Targets & protections (as of 2026-08-29)

Measured performance profile of the kal early-fly arm (`w25_5m_m0_kal_ef5`,
the full 54-session restated ledger, canonical all-in cost model). This is
the yardstick the live forward test is judged against.

| Metric | Value |
|---|---|
| Total all-in P&L | $24,773 / 202 cycles |
| Cycle win rate | 43.1% (87/202) |
| Day win rate | 62% (31 up / 19 down, 50 traded days) |
| Avg winner / avg loser | $533 / −$188 (2.83 : 1) |
| Median winner / loser | $328 / −$165 |
| Largest win / largest loss | $2,452 / **−$612** |
| Profit factor | 2.15 (gross $46,370 / −$21,597) |
| Daily mean / stdev | $459 / $1,055 |
| Sharpe (annualized, daily) | 6.9 |
| Sortino (annualized, daily) | 29.1 |
| Max drawdown | −$1,460 on $24,773 cumulative |

**Margin expectations (planning):** the day's peak concurrent buying-power
reduction, from the same 50 traded days (open verticals hold width − credit;
completed lossless flies hold $0; early-fly deficits hold the bounded
deficit to settlement). Now a per-day scoreboard column (HW margin).

| Arm | Median | p90 | Max |
|---|---|---|---|
| kal 25-wide | $1,851 | $2,023 | $2,078 |
| kal 25-wide early-fly | $1,860 | $2,078 | $3,158 |
| kal 50-wide | $4,174 | $4,502 | $4,538 |

Rule of thumb: a one-lot 25-wide needs ~$2k of buying power ($3.2k worst
observed when a deficit fly overlapped a fresh vertical); a 50-wide needs
~$4.5k. Return on peak capital is extreme because the capital is only at
risk until the fly locks.

**The structural loss cap is the essential feature.** The worst cycle in 54
sessions lost $610 and the deepest equity drawdown was $1,449 — on a strategy
that made $24.8k — with **no stop-loss anywhere**. The cap is built from
three layers of the structure itself, not from a risk rule bolted on top:

1. **Defined-risk vertical:** max theoretical loss is width − credit,
   ~$1,500–1,700 on a 25-wide, before any exit fires.
2. **Either-flip exit:** the position closes on the first kalman *or* hull
   flip against it, cutting errant spreads long before max loss — realized
   losses cluster at $150–250, a fraction of the theoretical cap.
3. **Early-fly conversion (5 pts adverse):** converts a losing vertical into
   a bounded-deficit fly, capping the cycle while keeping the tent alive.

This is why Sortino (29) dwarfs Sharpe (6.9): the volatility is almost
entirely upside. Losses are small, frequent, and bounded; the P&L lives in
the right tail (in-tent settlements: 42 cycles, +$28.8k; the 160 flip-exited
cycles net −$4.0k combined — the cost of holding lottery tickets).

**Where the win rate lives:** 44% per cycle is the *expected* shape — the
strategy scratches often (152 kalman-flip closes net −$6.3k, hull backstop
+$2.4k) and is paid by tents at 2.73:1. Judge the forward test on profit
factor and the loss cap holding, not on cycle win rate.

**Targets, execution-adjusted:** mid-fill resim overstates fillable edge
(see 2026-08-29 execution-sensitivity finding). Planning band for the
25-wide family is the persistence-haircut range, ~76–100% of the numbers
above; the fill-persistence arms (`_p2`/`_p4`) accumulate the live bound.

**Protections that must hold live (violations are red flags, not noise):**
- No single cycle loses more than ~$700 (worst observed −$610).
- Drawdown materially past ~$1.5k means the regime, not the luck, changed —
  stop and re-characterize before continuing.
- No stop-loss gets added, ever: four independent falsifications (stops,
  defer-to-fade, bank-on-fade, credit-trailing) all subtract. The flip exit
  and the early-fly conversion *are* the stop.

## Findings log

### 2026-09-05 — Kalman Velocity Trend Filter proposal replayed: no cell beats production robustly; the entry delay gives back what loser removal saves

**Proposal** (docs/Kalman Velocity Trend Filter Proposal - Updated.pdf, Rev 1.1;
ticket TT-180): keep the kalman direction but gate entries on standardized
velocity (KSV = v / sqrt(P_vv)) and the Kaufman efficiency ratio (ER), exit
by hysteresis at a lower hold threshold, arm that exit with a velocity-decay
warning, and veto entries under a sticky CHOP latch on repeated sign flips.

**Method.** Replay over 56 sessions (2026-06-11 → 09-04, settled at the
official close; 06-23, 06-24 and 06-29 lack a daily candle or snapshots) on
top of the production rule — kalman flip entries 10:00–13:00, either-family
flip exits kept as the backstop in every cell, lock-ASAP completion, 15:45
forced close, tents held to settlement, all-in cost model. One feature at a
time, 82 cells × 2 widths. Rig and results archived at
`research_data/TT-156/kalman_trend_filter_sweep_20260905.{py,_results.json,_report.txt}`.

**Calibration fact first.** With r fixed at 1 and q/r = 0.025 the posterior
velocity variance converges to a constant, σ_v = 0.278 pts/bar. KSV is
therefore raw velocity in units of 0.278 pts/bar, not an adaptive z-score,
and the proposal's 1.0–2.0 thresholds sit at the flip bar's own |KSV|
(median 1.24 at the flip, 2.85 one bar later, 4.35 across the entry
window). The grid was extended to 8 so the gate was tested where it bites.

25-wide (production 25-wide: $17,862 over 225 cycles, 20 tents):

| Test | Cell | Total | Cycles | Tents |
|---|---|---|---|---|
| A · KSV wait gate | θ 1.0 / 1.5 / 2.0 / 3.0 / 6.0 | $20,375 / $18,817 / $13,484 / $12,021 / −$200 | 197 / 186 / 173 / 158 / 109 | 19 / 18 / 14 / 13 / 6 |
| G · KSV flip-bar veto, no wait | θ 1.0 / 1.25 / 1.5 | $18,273 / $16,561 / $11,520 | 126 / 110 / 96 | 16 / 15 / 12 |
| B · ER gate (20 cells) | best er6 > 0.20; er8 > 0.30 | $12,130; $4,910 | 200; 163 | 15; 13 |
| C · KSV + ER (12 cells) | best θ1.5, er6 > 0.25 | $9,270 | 181 | 12 |
| D0 · hysteresis exit, production entries | hold 0.5 / 1.0 / 3.0 | $15,530 / $12,620 / −$80 | 286 / 360 / 758 | 20 / 20 / 17 |
| D · KSV + hysteresis (9 cells) | best θ1.5, hold 1.0 | $17,826 | 202 | 17 |
| E0 · armed decay exit, production entries | hold 0.5 / 1.0 | $16,187 / $14,640 | 264 / 302 | 20 / 20 |
| E · KSV + armed decay (9 cells) | best θ1.5, hold 0.5 | $17,875 | 191 | 18 |
| F · CHOP veto (7 cells) | alone; with θ1.5 | $14,139; $15,697 | 218; 182 | 18; 17 |

50-wide (production: $14,714, 225 cycles, 3 tents): A θ1.0 $15,453, θ1.5
$13,511; G θ1.25 $17,042 (110 cycles); B best $10,991; C best $8,418; D0
hold 0.5 $12,531; D best $14,866; E best $14,645; F $13,373.

Splits for the only family at or above production (A, θ 1.0): first half
$17,512 vs $15,377, second half $2,863 vs $2,485 on 25-wide; $10,278 vs
$10,087 and $5,174 vs $4,626 on 50-wide. Per session 24 better, 18 worse,
14 unchanged; largest daily swing ±$660. The ridge is one cell wide — θ
1.25 is already below production on 50-wide.

**Mechanism (paired by baseline flip).**

- *Wait gate (A).* At θ 1.0 the 28 baseline cycles it never enters net
  −$5,307 and include no tent; but the 197 it keeps enter 0.4 bars later on
  average and earn $20,375 against $23,169 for the same cycles at the flip.
  The delay gives back $2.8k of the $5.3k saved. At θ 1.5 it saves $7,168
  and gives back $6,213.
- *Flip-bar veto (G).* The flip bar's own |KSV| carries no information:
  vetoing 99 of 225 flips at θ 1.0 drops cycles that net −$411 in total
  (4 tents among them). It is the following bars — the flip failing to
  strengthen — that identify the losers, and using that information means
  entering later.
- *Hysteresis / decay exits (D0, E0).* On the same 225 cycles the earlier
  exit is nearly neutral (kept-cycle P&L $17,054–$18,129 vs $17,862): as
  with the fade exit, the vertical's mark barely moves between the hold
  breach and the flip. The state machine's re-entries (61 to 533 extra
  cycles) lose $1.5k–$13k. Tents are unaffected because they are already
  locked.
- *ER and CHOP.* Forfeit tents (20 → 15 or fewer) and never earn it back.

**Verdict — not adopted.** The seventh falsification of the same instinct
(stops, defer, bank, credit-trail, fade exit, completion geometry): what
looks like a weak or deteriorating trend is also the path back to the
strike that completes the fly, and the tent is the edge. The mildest KSV
wait (θ 1.0–1.5, i.e. 0.28–0.42 pts/bar) is the only region at or above
production; it is one cell wide, within daily noise, and mixed on 50-wide.
It would need a live tracked arm to be believed, not a retro replay. No
change to the live grid.

### 2026-09-04 — Settlement was priced at a stale pre-close snapshot; ledger restated at the official SPX close

**How it surfaced.** The 2026-09-04 EOD fly (7685/7710/7735 calls, 15.78
debit) showed +$268 on the chart card while the close of 7718.60 sat one
point inside the upper breakeven, worth about +$21 all-in. The collector
settled at 7716.28 — the last chain snapshot at or before 16:00:00, taken
at 15:59:56 — and the index rose 2.3 points in the seconds after it.

**Scope.** The rule "last snapshot at or before 16:00" was structurally
wrong, not a one-off: a 15 s cadence makes the spot up to 15 s stale, and
the index's official close is only final ~4 minutes after 16:00 (checked
on five sessions: last change between 16:03 and 16:04). Recorded
settlement spot vs the official close over 56 settled sessions:

| Measure | Value |
|---|---|
| Median absolute miss | 1.48 pts |
| Sessions missing by more than 2 pts | 21 of 56 |
| Largest miss | 15.63 pts (2026-06-26, recorded 7338.39 vs 7354.02) |

**Restatement (gross points × $100, every settled row re-priced at the
official close; 108 session directories incl. the pre-fix archive, 381
rows rewritten; 2026-06-23/24 have no daily candle and no settled rows):**

| Arm | Before | After | Difference |
|---|---|---|---|
| `w25_5m_m0_kal` (25-wide tents, 39) | $28,841 | $27,303 | −$1,538 |
| `w50_5m_m0_kal` (50-wide tents, 4) | $7,193 | $7,147 | −$46 |
| `w25_5m_m0_kal_ef5` | $30,200 | $28,783 | −$1,417 |
| `pinfly25_all` (live sessions, 4) | $2,176 | $2,078 | −$98 |
| `pinfly25_notent` | $1,514 | $1,370 | −$144 |
| `pinfly25_notent_mid` | $478 | $608 | +$130 |

Seventeen structures moved by $100 or more; the largest was the 2026-06-26
25-wide, recorded +$85, actually +$1,427. The 25-wide tent count moved
from 19 to 20. No strategy conclusion changes; every retro sweep that read
`recorded_settlement` inherited the stale spots and now reads the restated
values without change.

**Rule going forward.** Settlement price = official SPX close (daily
candle, date-checked so the provider's walk-back to a prior day can never
substitute). No fallback: an unavailable close leaves the day unsettled.
The restatement was a one-off; the script that ran it is archived with the
other rigs at `research_data/TT-156/restate_official_close_20260904.py`
and the pre-rewrite ledger at
`research_data/TT-156.pre-restate-20260904-165110/`.

### 2026-09-03 — The every-session 14:00 fly earns on tent days too; its place is justified, the no-tent half is the stronger half

Purpose of the no-tent arms was always this split. Replayed the 14:00
ATM 25-wide call fly at mid from the recorded 14:00 snapshot across 55
sessions (2026-06-11 → 09-02), settled to the recorded settlement (32),
the 15:59 1m close (21) or the last snapshot (2), all-in, and split by
whether a 25-wide kalman tent existed at 14:00 (live ledger; 3 sessions
lack a kalman ledger).

| Sessions | n | total | mean | median | win rate | worst | best |
|---|---|---|---|---|---|---|---|
| all | 55 | $14,214 | $258 | $328 | 73% | −$1,299 | $1,392 |
| tent existed at 14:00 | 26 | $4,026 | $155 | $134 | 65% | −$1,169 | $1,392 |
| no tent at 14:00 | 26 | $8,049 | $310 | $545 | 77% | −$1,299 | $1,033 |
| first half / second half | 27 / 28 | $5,859 / $8,355 | | | 67% / 79% | | |

Reading: the fly is not a drag on tent days — it nets +$4k over 26 with
a 65% hit rate — so buying it every session (decision 2026-09-03) costs
nothing in expectation and adds a second, independent afternoon-pin
payoff on days the tent already exists. The no-tent half is the stronger
half (double the mean, four times the median), which is what the
cushion logic predicted: no tent usually means a choppy, range-bound day,
the fly's home regime. The tent-day losers are the trend days that run
through both structures. Both halves are positive out of sample. Rig:
pinfly_tent_split (session scratch); results JSON under research_data/TT-156/.

### 2026-09-03 — "Better tents": completion geometry, entry offset, and a runaway classifier all falsified; one candidate for a tracked arm

Prompted by today's 10:50 25-wide: locked at 11:11 with spot already
7728.8 on a 7680/7705/7730 tent, spot then ran to 7748 and the tent was
worth scratch while the uncompleted 50-wide rode the same move to +8.17
pts at the 11:45 flip. Three parallel replays over the 54–56 settled
sessions (kalman entries, either-family exits, lock-ASAP, all-in, per arm,
IS = first 27 sessions / OOS = the rest). Timing was deliberately NOT
retested (four prior falsifications, 2026-08-28).

**Completion geometry (what counter to sell at the lossless instant):
falsified by construction.** Surplus at lock (total credit − width) over
42 flies: median 0.20 pts, p90 0.70. A shifted or wider counter is also
lossless in 2 of 42 flies; every rule collapses to the baseline (25-wide
within +$310, zero OOS divergence; 50-wide identical). The freebie is a
momentum spike that pushes total credit to exactly the width; any other
geometry needs more travel first, i.e. deferral. Today at 11:11 the
one-strike shift was 1.53 pts short, a 30-wide counter 2.12 pts short.

**Entry strike offset (k strikes OTM/ITM so the tent centers further along
the move): falsified.** Completion timing is invariant to k (all six
offsets locked at the same snapshot today); the offset only slides a fixed
tent against a settlement that is not predictable to ±10 pts. 25-wide:
1 OTM +$4,005 in aggregate but median day $0, median cycle +$15, five days
carry it; ITM offsets monotonically worse and negative OOS. 50-wide 3 ITM
+$8,994 with median cycle −$55 (125 losers / 72 winners) — the half-width
credit-leverage tail, not tent quality.

**Runaway classifier at the lossless moment (1m/5m velocity and its
change, spot−K, minutes since entry/open, OR15/OR30 distance, drive_atr,
retrace_frac, range/ATR, surplus): the fifth falsification.** 38 25-wide
flies, 21 settle in tent (55%, avg $1,301) vs $10 outside; ride-instead
total $15,855 vs tent $27,502. No feature exceeds AUC 0.6, and the
intuitive ones point the wrong way: 15 flies locked with spot already past
the far wing, 9 of those still settled in the tent (riding them nets
−$1,723); strong 1m/5m velocity at lock leans toward in-tent. Today's lock
scored drive 0.71 / retrace 0.79 → complete, exactly what production did.

**One survivor, tracked-arm grade only:** when the freebie arrives as
price reclaims the open (rolling drive_atr < ~0.23 with retrace_frac
saturated), 6 of 8 flagged cycles ran through by 30–45 pts; tent $2,010 vs
ride $5,093 over the 8 (IS +$1,787 / OOS +$1,294, permutation p = 0.03
for the whole select-then-score procedure). Eight cycles from a
14-feature grid confirmed on two OOS cycles: needs forward evidence, not
a rule change.

Conclusion: today's tent was a regime cost, not a rule defect. Lock-ASAP
same-strike stays. Rigs: tent_geometry_sweep, entry_offset_sweep,
runaway_classifier (session scratch); result JSONs archived under
research_data/TT-156/.

### 2026-09-02 — OR-conditioned early entry falsified; the 10:00 start survives

Tested (user speculation after today's missed morning move): open the
entry window from 09:35 when a sealed 5m close breaks the opening range
in the kalman direction — the flip arms, the breakout confirms. 54-session
replay, primary arms, all-in.

5m-OR confirm: worse everywhere (32 triggers, −$605/−$812/−$1,483 vs
control). 15m-OR confirm: +$1,484 on the 25-wide in aggregate — but the
decomposition kills it: 23 trigger days split 6 improved / 17 hurt, the
entire gain sits in three days, the 50-wide loses $2,787 outright, and the
early cycles produce losses of −$705 to −$1,210 — through the structural
cap that the strategy's economics depend on (worst-ever regular cycle:
−$612). The first 30 minutes is churn even when an OR breakout with
kalman agreement says otherwise; the rare early monster is a tail masking
a habitual bleed, the same shape as the defer/bank/trail falsifications.
The hard 10:00 start stays. Rig: or_entry_sweep (session scratch);
results JSON archived with the sweep.

### 2026-08-31 — Feed-lag incident: a lagged candle stream poisons the filter state (not just delays it)

Day one of the kalman-primary forward test hit a DXLink degradation: from
the open-volume ramp (~09:35 ET) the shared candle stream fell ~55 minutes
behind wall clock while staying connected — no disconnect, no reconnect,
events still flowing, every bar late. The collector sealed no 5m bar after
09:55 and the charts froze.

**The key finding came from comparing the live trace against a clean-history
replay: the live engine didn't just trade late, it traded the WRONG
direction.** The corrupted stream (one bar mutating for an hour, then a
compressed catch-up burst) left the kalman/hull recursions in a state that
disagreed with the clean-data recursion — live read the 11:40 flip as
bullish; the truth was bearish. A lagged stream poisons filter state.
Detection must therefore act on bar-TIME staleness (TT-157's watchdog
criterion), not event arrival, and recovery must rebuild engine state from
clean history, never resume a poisoned recursion.

Fixes shipped same day: TT-164 two-tier candle channels (configured fast
pool — SPX 1m/5m — at 0.1s firehose; every other subscription conflated at
1.0s, ~10x wire reduction on 24/36 subscriptions). Ledger cleaned by
replaying the broken window from recorded chains + true candle timing and
keeping the healthy-feed live trades (12:25 onward) verbatim. Day result:
chop, six flip-exit scratches, no tents (kal 25-wide -$662 all-in). Note:
the scoreboard's HW-margin cells for this date are inflated by a 3-minute
merge-seam overlap ($3,600 vs a real ~$1,800).

### 2026-08-29 — Cost model recalibrated to real fills; margin high-water tracked

Pulled the actual fee breakdown from a live SPXW 2-leg vertical in the
account (2026-08-26): opening spread $3.44 all-in ($1.00 commission x2 legs
+ $0.10 clearing + $0.02 regulatory + $0.60 CBOE proprietary index fee per
leg), closing spread $1.44 (no commission on closes). The old model assumed
$5 flat per spread order. Slippage raised from 0.075 to 0.10 per spread
(user fills 0DTE at ~0.05; 0.10 is the guarantee-the-fill buffer). Net
effect ≈ a wash: the extra $2.50 slippage per spread offsets the fee
overstatement almost exactly (kal early-fly 54-session total moved $24,833
→ $24,773). All reports and the scoreboard restated; the scoreboard also
gained per-day HW-margin columns for the primary 25/50-wide arms (see
Targets & protections for the planning numbers).

### 2026-08-29 — Execution sensitivity: how much edge survives if ephemeral freebies don't fill

User concern (raised after the trailing tests kept failing on short-lived
spikes): is the edge itself built on untradable one-tick touches? Measured
directly. Dwell of the 38 baseline 25-wide freebies from first touch: 16
lasted a single 15s snapshot, 8 lasted 30–60s, 14 persisted over a minute.
Persistence haircut (completion only counts if the freebie survives N
snapshots): N=2 (30s) → $17,128 / 32 flies; N=4 (60s) → $16,230 / 28 flies,
vs $21,298 / 38 at baseline. The 50-wide is untouched (~$16.1k at every N —
its completions are all slow moves).

**Reading:** ~42% of completions are ephemeral touches and assuming them
unfillable costs ~24% of the edge — real, but not fatal: the worst case
still runs 2.3x the hull baseline, because missed one-tick completions
become later completions or flip exits (not losses) and the monster tents
come from sustained moves whose freebies persisted for minutes. Live
completion is a resting limit order, so truth sits between N=1 and N=4.
**Planning number: the $16–17k band, not $21k.** Final resolution requires
real fills — a one-lot live test, which no mid-price resim can substitute
for.

### 2026-08-28 (late) — The tent IS the edge: never trade the lottery ticket for a certain profit

Tested the appealing idea of not locking the fly the instant it's free —
holding while velocity still builds so the same fly locks at a *guaranteed*
profit, or banking the entry vertical's profit when momentum fades. Both
versions lose (53 sessions, 25-wide: lock-ASAP $21,298 vs defer-to-fade
$18,051 vs bank-on-fade $11,783).

**The essential takeaway, visible in the per-cycle ledger of the 28 diverged
trades:** deferring/banking is implicitly a bet that settlement will miss the
tent. It wins more often — 15 of 28 cycles, +$200–600 each, exactly the flies
that settle at or outside the wings — but the 13 it loses are the flies that
settle **inside the tent**, worth $675–2,454 (avg ≈ $1,090). Selling that
lottery ticket for a ~$350 certain profit costs double what it earns, because
in this regime settlement lands inside the tent often enough to pay for
everything. The velocity fade is a good profit marker but an unreliable
trend-end marker (several banked cycles saw the trend resume into a
$2k tent without the position).

This is the third independent falsification of the same instinct — stops
(every level subtracts), defer-completion, bank-on-fade — and they all fail
the same way: **the strategy's economics live in the right tail (in-tent
settlements). Lock the fly the moment total credit ≥ width; hold every tent
to settlement.** Any rule that caps, delays, or substitutes for the tent
underperforms.

**Fourth falsification (credit-trailing with a floor guard):** even a
maximally protective deferral — trail the 15s counter-credit high-water
mark, lock on a G-point giveback OR the instant total decays back to the
width (never surrender the freebie) — loses ~$5.5–5.9k across G ∈
{0.5, 1, 2} on the 25-wide (31 vs 38 flies). Root cause: ~25 of the armed
freebies existed for a single 15-second snapshot, and the first touch of
width typically occurs on a momentum spike when the counter credit is at a
local peak — waiting from there has downhill expected drift. The credit
stall and the freebie are the same event; lock-ASAP is the trailing rule
with zero giveback, and zero is optimal.

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
