"""
Subscription management module for TastyTrade market data feeds.

This module provides the CLI tool for managing market data subscriptions,
including historical backfill, live streaming, and operational monitoring.
"""

from tastytrade.subscription.cli import cli

__all__ = ["cli"]
