"""Tiny dev server that serves static files AND supports PUT for saving JSON layouts.

Usage:
    python _devserver.py [port]          # default: 8765
    python _devserver.py 9000

Serves the current directory. PUT requests write the body to the requested file path
(restricted to .json files in the served directory for safety).

API endpoints:
    POST /api/refresh — re-export trade data and market data from Redis to JSON files.
    WS   /api/claude  — bridges browser xterm.js to a local `claude --continue` PTY,
                        so the review playground can drive the user's running Claude
                        Code session. See TT-127.
"""

import base64
import hashlib
import json
import os
import socket
import struct
import sys
import threading
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


# =============================================================================
# WebSocket framing (RFC 6455) — minimal text/binary support for the
# /api/claude PTY bridge. Hand-rolled to avoid pulling websockets/asyncio into
# the otherwise-sync http.server.
# =============================================================================

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def ws_recv_exactly(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def ws_read_frame(sock: socket.socket) -> tuple[int, bytes] | None:
    """Read one WebSocket frame. Returns (opcode, payload) or None on close/error."""
    header = ws_recv_exactly(sock, 2)
    if header is None:
        return None
    byte1, byte2 = header[0], header[1]
    opcode = byte1 & 0x0F
    masked = (byte2 & 0x80) != 0
    length = byte2 & 0x7F
    if length == 126:
        ext = ws_recv_exactly(sock, 2)
        if ext is None:
            return None
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = ws_recv_exactly(sock, 8)
        if ext is None:
            return None
        length = struct.unpack("!Q", ext)[0]
    mask_key = b""
    if masked:
        mk = ws_recv_exactly(sock, 4)
        if mk is None:
            return None
        mask_key = mk
    payload = ws_recv_exactly(sock, length) if length else b""
    if payload is None:
        return None
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return (opcode, payload)


def ws_send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    """Send one unfragmented frame from server (no masking, FIN=1)."""
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < (1 << 16):
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    sock.sendall(bytes(header) + payload)


def find_repo_root() -> Path:
    """Walk up from this file to the repo root (where .git lives)."""
    p = Path(__file__).resolve()
    for ancestor in [p, *p.parents]:
        if (ancestor / ".git").exists():
            return ancestor
    return Path(__file__).resolve().parent.parent.parent


def bridge_ws_to_claude_pty(sock: socket.socket) -> None:
    """Spawn `claude --continue` in a PTY and bridge stdin/stdout to the websocket.

    Wire protocol:
      - BINARY frames in both directions carry raw PTY bytes (terminal I/O).
      - TEXT frames carry JSON control messages from the client. Currently
        only `{"type":"resize","rows":N,"cols":N}` is recognised.
    """
    import ptyprocess

    repo_root = find_repo_root()
    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")

    try:
        proc = ptyprocess.PtyProcess.spawn(  # type: ignore[attr-defined]
            ["claude", "--continue"],
            cwd=str(repo_root),
            env=env,
            dimensions=(40, 120),
        )
    except Exception as exc:
        try:
            ws_send_frame(
                sock,
                OP_TEXT,
                json.dumps({"error": f"failed to spawn claude: {exc}"}).encode(),
            )
            ws_send_frame(sock, OP_CLOSE, b"")
        except OSError:
            pass
        return

    pty_fd = proc.fd
    stop = threading.Event()

    def pty_to_ws() -> None:
        try:
            while not stop.is_set():
                try:
                    data = os.read(pty_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                try:
                    ws_send_frame(sock, OP_BINARY, data)
                except OSError:
                    break
        finally:
            stop.set()

    def ws_to_pty() -> None:
        try:
            while not stop.is_set():
                frame = ws_read_frame(sock)
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == OP_CLOSE:
                    break
                if opcode == OP_PING:
                    try:
                        ws_send_frame(sock, OP_PONG, payload)
                    except OSError:
                        break
                    continue
                if opcode == OP_TEXT:
                    try:
                        msg = json.loads(payload.decode("utf-8", errors="replace"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                    if isinstance(msg, dict) and msg.get("type") == "resize":
                        try:
                            rows = int(msg["rows"])
                            cols = int(msg["cols"])
                            proc.setwinsize(rows, cols)
                        except (KeyError, ValueError, OSError):
                            pass
                    continue
                if opcode == OP_BINARY:
                    try:
                        os.write(pty_fd, payload)
                    except OSError:
                        break
        finally:
            stop.set()

    t1 = threading.Thread(target=pty_to_ws, name="claude-pty->ws", daemon=True)
    t2 = threading.Thread(target=ws_to_pty, name="claude-ws->pty", daemon=True)
    t1.start()
    t2.start()
    try:
        stop.wait()
    finally:
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass
        try:
            ws_send_frame(sock, OP_CLOSE, b"")
        except OSError:
            pass
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        t1.join(timeout=2)
        t2.join(timeout=2)


class DevHandler(SimpleHTTPRequestHandler):
    """Extends SimpleHTTPRequestHandler with PUT and API support."""

    def do_GET(self) -> None:
        if self.path == "/api/claude" and (
            self.headers.get("Upgrade", "").lower() == "websocket"
        ):
            self.handle_claude_upgrade()
            return
        super().do_GET()

    def handle_claude_upgrade(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        version = self.headers.get("Sec-WebSocket-Version", "")
        if not key or version != "13":
            self.send_error(400, "Bad WebSocket upgrade")
            return
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()
        ).decode()
        self.close_connection = True  # do not let BaseHTTPRequestHandler reuse
        self.wfile.write(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            ).encode()
        )
        self.wfile.flush()
        try:
            bridge_ws_to_claude_pty(self.connection)
        except Exception as exc:
            self.log_message("WS /api/claude bridge error: %s", exc)

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
    print(f"WS  /api/claude  bridges to `claude --continue` from {find_repo_root()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
