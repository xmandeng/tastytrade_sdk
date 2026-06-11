# TT-156 Research Day Runbook — 0DTE SPX Lossless-Butterfly Legging

**Ticket:** TT-156 · **Branch:** `feature/TT-156-0dte-butterfly-research`
**Nature of work:** PAPER ONLY — no orders are ever placed. The harness collects
live 0DTE chain pricing and simulates fills at mid-price.

## What runs

`uv run python -m research.tt156_zero_dte_butterfly.run_day` (from repo root, on the
feature branch). The process:

1. Warms up the Hull/MACD engine from InfluxDB history (SPX 1m + 5m).
2. Subscribes to live Redis candle channels (`market:CandleEvent:SPX{=m}` / `{=5m}`).
3. Waits for 09:28 ET, resolves the SPXW 0DTE chain (spot ±160 pts), writes
   `header.json` (incl. prior OHLC + GEX levels).
4. Every 15s until 16:15 ET: snapshots the full chain (bid/ask/Greeks/IV/OI via
   batched REST `/market-data/by-type`), records engine state, feeds the paper
   simulator (12 variants: width 10/25/50 × signal 1m/5m × margin 0/2 pts).
5. At 16:15: settles completed butterflies at the 16:00 SPX print, writes
   `final_results.json`, exits. **Process exit ≈ 16:15 ET is normal.**

Data dir: `research_data/TT-156/<YYYY-MM-DD>/` (gitignored).

## Pre-flight (09:20 ET)

1. `redis-cli ping` → PONG.
2. Feed alive: `redis-cli HGET tastytrade:latest:CandleEvent "SPX{=m}"` — the
   candle `time` should be recent (pre-market may lag; by 09:30 it must be fresh).
   The subscribe service runs in tmux session `tasty` (`just account-stream` +
   `tasty-subscription run ... --symbols ...,SPX`). If it is down, restart it in
   tmux before launching the collector.
3. `git status` — be on `feature/TT-156-0dte-butterfly-research`.
4. Launch the collector as a background task from the repo root.

## Monitoring during the day

- `research_data/TT-156/<date>/health.json` — rewritten every cycle. Healthy:
  `cycles` increasing, `quotes_in_last_snapshot` ≥ 120, `ts` within ~1 min,
  `spot` tracking the market.
- `events.jsonl` — one line per ENTRY / COMPLETION / CLOSE / SETTLEMENT.
- `collector.log` — exceptions are logged and the loop continues; repeated cycle
  failures are the thing to investigate.
- Signals only fire 10:00–15:00 ET (engine entry gates); CLOSE signals fire
  any time after 10:00.

## Contingencies

- **Collector crash:** relaunch the same command. Snapshots and events append —
  but open paper positions are lost (simulator state is in-memory). Note the
  restart time; the EOD retro-sweep is unaffected (it replays the snapshot file).
- **Recovery accounting rule (binding): no backdated fills.** Positions ride
  unmanaged through any outage; orphaned structures may only be exited at or
  after the first post-recovery snapshot, at that snapshot's quotes. A real
  deployment should additionally park hard stops broker-side (GTC), since
  resting orders are the only thing that can fill while your software is dead.
- **Candle stream stale:** spot falls back to REST automatically; chain capture
  is unaffected. Hull/MACD signals stall though — note the gap. Check the tmux
  `tasty` session / reconnect behavior of the subscribe service.
- **Redis down:** collector cannot start (config + candles need it). Restart
  Redis (docker compose) and relaunch.

## End of day (after the process exits, ~16:16 ET)

1. `uv run python -m research.tt156_zero_dte_butterfly.report research_data/TT-156/<date>`
2. Read `REPORT.md` + `final_results.json` + `retro_sweep.json`.
3. Summarize for the user: per-variant results, completion rates from the
   retro-sweep, required-move observations, honest alpha assessment (single
   day, mid-fill caveats).
4. Add an implementation comment to TT-156 via the jira-workflow agent
   (Expected Behaviors, Technical Implementation, Features, Verification
   Evidence — per CLAUDE.md completion documentation).
5. Delete the TT-156 kickoff/midday cron jobs (CronList → CronDelete).

## Strategy mechanics being tested (for context)

Entry: confluence OPEN signal → sell ATM vertical at mid
(BEARISH → bear call K/K+w; BULLISH → bull put K/K-w), credit C1.
Completion: when the counter vertical at the same short strike K fetches C2
with C1+C2 ≥ w (+margin), sell it → iron butterfly with locked worst-case
P&L = C1+C2−w ≥ 0, best case C1+C2 at a pin on K.
If never completed: close on opposing CLOSE signal or forced close 15:45 ET.
Settlement: completed flies held to the 16:00 print; payoff
= C1+C2 − min(|S−K|, w).
