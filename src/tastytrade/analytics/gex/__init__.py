"""GEX (Gamma Exposure) snapshot backend — TT-139.

Symbol- and expiration-agnostic point-in-time GEX computation over the
Tastytrade REST API. v1 covers equity-options (SPX 0DTE is the validation
target); futures-options is post-v1. See docs/plans/TT-138-gex-snapshot.md.
"""

from tastytrade.analytics.gex.client import (
    EQUITY_OPTION_MULTIPLIER,
    STRIKE_WINDOW_PCT,
    SymbolContext,
    fetch_chain_for_expirations,
    fetch_option_market_data,
    fetch_spot,
    resolve_symbol_context,
)
from tastytrade.analytics.gex.compute import aggregate_by_strike, compute_option_gex
from tastytrade.analytics.gex.levels import Levels, identify_levels
from tastytrade.analytics.gex.snapshot import (
    SnapshotEnvelope,
    snapshot_key,
    take_snapshot,
)

__all__ = [
    "EQUITY_OPTION_MULTIPLIER",
    "STRIKE_WINDOW_PCT",
    "SymbolContext",
    "resolve_symbol_context",
    "fetch_spot",
    "fetch_chain_for_expirations",
    "fetch_option_market_data",
    "compute_option_gex",
    "aggregate_by_strike",
    "Levels",
    "identify_levels",
    "SnapshotEnvelope",
    "snapshot_key",
    "take_snapshot",
]
