"""Live charting module — TOS-style interactive charts with real-time updates.

Standalone component that composes existing SDK infrastructure:
- InfluxDB for historical candle data (MarketDataProvider)
- Redis pub/sub for live candle + annotation events
- Hull MA and MACD indicator computation

Usage:
    # CLI
    tasty-chart --symbol SPX --interval 5m

    # Library
    from tastytrade.charting.server import ChartServer
    server = ChartServer(symbol="SPX", interval="1m")
    await server.start(port=8080)
"""
