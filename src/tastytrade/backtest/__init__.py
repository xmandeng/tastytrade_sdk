"""Backtesting framework for signal engine strategies.

Replays historical candle data through signal engines via Redis pub/sub,
producing BacktestSignal events distinguishable from live TradeSignals
in both Redis channels and InfluxDB measurements.

Architecture (all communication through Redis):
    BacktestReplay  → Redis backtest:CandleEvent:*  (InfluxDB → Redis)
    BacktestRunner  → Redis market:BacktestSignal:* (Redis → Engine → Redis)
    BacktestFeed    → InfluxDB                      (Redis → InfluxDB)
"""

from tastytrade.backtest.models import BacktestConfig, BacktestSignal
from tastytrade.backtest.publisher import BacktestPublisher
from tastytrade.backtest.replay import BacktestReplay
from tastytrade.backtest.runner import BacktestRunner

__all__ = [
    "BacktestConfig",
    "BacktestPublisher",
    "BacktestReplay",
    "BacktestRunner",
    "BacktestSignal",
]
