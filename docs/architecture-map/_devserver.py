"""Tiny dev server that serves static files AND supports PUT for saving JSON layouts.

Usage:
    python _devserver.py [port]          # default: 8765
    python _devserver.py 9000

Serves the current directory. PUT requests write the body to the requested file path
(restricted to .json files in the served directory for safety).
"""

import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class DevHandler(SimpleHTTPRequestHandler):
    """Extends SimpleHTTPRequestHandler with PUT support for .json files."""

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
    server = HTTPServer(("0.0.0.0", port), DevHandler)
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
