"""Tiny dev server that serves static files AND supports PUT for saving JSON layouts.

Usage:
    python _devserver.py [port]          # default: 8765
    python _devserver.py 9000

Serves the current directory. PUT requests write the body to the requested file path
(restricted to .json files in the served directory for safety).

API endpoints:
    POST /api/refresh — re-export trade data and market data from Redis to JSON files.
"""

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def refresh_from_redis() -> dict[str, str]:
    """Pull fresh data from Redis and write JSON files. Returns status."""
    import asyncio

    import redis.asyncio as aioredis  # type: ignore[import-untyped]

    results: dict[str, str] = {}

    async def export() -> None:
        r: aioredis.Redis = aioredis.Redis()  # type: ignore[type-arg]
        try:
            # raw_redis_data.json — orders, trade chains, positions
            raw_orders = await r.hgetall("tastytrade:orders")
            orders = []
            for key, val in raw_orders.items():
                k = key.decode() if isinstance(key, bytes) else key
                orders.append({"redis_key": k, "raw": json.loads(val)})

            raw_chains = await r.hgetall("tastytrade:trade_chains")
            chains = []
            for key, val in raw_chains.items():
                k = key.decode() if isinstance(key, bytes) else key
                chains.append({"redis_key": k, "raw": json.loads(val)})

            raw_pos = await r.hgetall("tastytrade:positions")
            positions = []
            for key, val in raw_pos.items():
                k = key.decode() if isinstance(key, bytes) else key
                positions.append({"redis_key": k, "raw": json.loads(val)})

            trade_data = {
                "redis_keys": {
                    "orders": "tastytrade:orders",
                    "trade_chains": "tastytrade:trade_chains",
                    "positions": "tastytrade:positions",
                },
                "orders": orders,
                "trade_chains": chains,
                "positions": positions,
            }
            Path("raw_redis_data.json").write_text(
                json.dumps(trade_data, indent=2, default=str)
            )
            results["raw_redis_data"] = (
                f"{len(orders)} orders, {len(chains)} chains, {len(positions)} positions"
            )

            # market_data.json — greeks, quotes, instruments
            raw_greeks = await r.hgetall("tastytrade:latest:GreeksEvent")
            greeks = {}
            for key, val in raw_greeks.items():
                k = key.decode() if isinstance(key, bytes) else key
                greeks[k] = json.loads(val)

            raw_quotes = await r.hgetall("tastytrade:latest:QuoteEvent")
            quotes = {}
            for key, val in raw_quotes.items():
                k = key.decode() if isinstance(key, bytes) else key
                quotes[k] = json.loads(val)

            pos_map = {}
            for _key, val in raw_pos.items():
                p = json.loads(val)
                sym = p.get("symbol", "").strip()
                pos_map[sym] = {
                    "underlying": p.get("underlying-symbol", ""),
                    "multiplier": p.get("multiplier"),
                    "streamer_symbol": p.get("streamer-symbol"),
                    "average_open_price": p.get("average-open-price"),
                }

            raw_inst = await r.hgetall("tastytrade:instruments")
            instruments = {}
            for key, val in raw_inst.items():
                k = key.decode() if isinstance(key, bytes) else key
                inst = json.loads(val)
                ss = inst.get("streamer-symbol", "")
                if ss:
                    instruments[k] = {"streamer_symbol": ss}

            market_data = {
                "greeks": greeks,
                "quotes": quotes,
                "positions": pos_map,
                "instruments": instruments,
            }
            Path("market_data.json").write_text(
                json.dumps(market_data, indent=2, default=str)
            )
            results["market_data"] = (
                f"{len(quotes)} quotes, {len(greeks)} greeks, {len(instruments)} instruments"
            )
        finally:
            await r.close()

    asyncio.run(export())
    return results


class DevHandler(SimpleHTTPRequestHandler):
    """Extends SimpleHTTPRequestHandler with PUT and API support."""

    def do_POST(self) -> None:
        if self.path == "/api/refresh":
            try:
                results = refresh_from_redis()
                body = json.dumps({"ok": True, "data": results}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                body = json.dumps({"ok": False, "error": str(e)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        self.send_error(404, "Not found")

    def do_PUT(self) -> None:
        # Only allow .json files in the served directory
        path = self.translate_path(self.path)
        rel = os.path.relpath(path, os.getcwd())

        if ".." in rel or not rel.endswith(".json"):
            self.send_error(403, "PUT only allowed for .json files in served directory")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            Path(path).write_bytes(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        except OSError as e:
            self.send_error(500, str(e))

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight for PUT requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        # Quieter logging — skip 200/304 GETs
        if len(args) >= 2 and str(args[1]) in ("200", "304"):
            return
        super().log_message(format, *args)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    import socket

    class ReusableThreadingHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True
        allow_reuse_port = True

        def server_bind(self) -> None:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            super().server_bind()

    server = ReusableThreadingHTTPServer(("0.0.0.0", port), DevHandler)
    print(f"DevServer running on http://localhost:{port}/")
    print(f"Serving: {os.getcwd()}")
    print("PUT enabled for .json files (layout persistence)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
