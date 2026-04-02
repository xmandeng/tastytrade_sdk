"""End-to-end chart server tests via Playwright (sync API).

Tests WebSocket connectivity, date switching responsiveness,
and disconnect handling.
Requires: chart server running on port 8091, Redis with candle data.
"""

import json
import time

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8091"


def collect_ws_frames(page):  # type: ignore[no-untyped-def]
    """Set up persistent WebSocket frame collector across reconnections."""
    frames: list[str] = []

    def on_ws(ws):  # type: ignore[no-untyped-def]
        ws.on("framereceived", lambda payload: frames.append(payload))

    page.on("websocket", on_ws)
    return frames


def wait_for_init(frames: list[str], page, timeout: float = 5.0) -> dict | None:  # type: ignore[no-untyped-def]
    """Poll frames list for an init message."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for raw in frames:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("type") == "init":
                    return data
            except (json.JSONDecodeError, TypeError):
                pass
        page.wait_for_timeout(100)
    return None


def change_date(page, date: str) -> None:  # type: ignore[no-untyped-def]
    """Trigger a date change via connect() — same as real user flow."""
    page.evaluate(f"connect('{date}')")


def test_chart_loads_with_candles() -> None:
    """Chart should load and receive init payload with candles."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        frames = collect_ws_frames(page)

        page.goto(f"{BASE_URL}/?symbol=SPX&interval=m")
        init_msg = wait_for_init(frames, page)

        assert init_msg is not None, f"No init message. Got {len(frames)} frames"
        assert init_msg["symbol"] == "SPX"
        assert len(init_msg["candles"]) > 0
        print(f"  PASS: Loaded {len(init_msg['candles'])} candles for SPX")

        page.close()
        browser.close()


def test_date_switch_to_prior() -> None:
    """Switching to a prior date should complete within 3 seconds."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        frames = collect_ws_frames(page)

        page.goto(f"{BASE_URL}/?symbol=SPX&interval=m")
        wait_for_init(frames, page)

        frames.clear()
        start = time.monotonic()
        change_date(page, "2026-03-31")
        init_msg = wait_for_init(frames, page)
        elapsed = time.monotonic() - start

        assert init_msg is not None, "Date switch to 3/31 did not complete"
        print(
            f"  PASS: Switch to 3/31 in {elapsed:.2f}s ({len(init_msg['candles'])} candles)"
        )
        assert elapsed < 3.0, f"Took {elapsed:.2f}s"

        page.close()
        browser.close()


def test_switch_back_to_today() -> None:
    """Switching back to today after a prior date should be fast."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        frames = collect_ws_frames(page)

        page.goto(f"{BASE_URL}/?symbol=SPX&interval=m")
        wait_for_init(frames, page)

        # Go to prior date
        frames.clear()
        change_date(page, "2026-03-31")
        wait_for_init(frames, page)

        # Switch BACK to today
        frames.clear()
        start = time.monotonic()
        change_date(page, "2026-04-01")
        init_msg = wait_for_init(frames, page, timeout=10.0)
        elapsed = time.monotonic() - start

        assert init_msg is not None, "Switch back to today did not complete"
        print(
            f"  PASS: Switch to today in {elapsed:.2f}s ({len(init_msg['candles'])} candles)"
        )
        assert elapsed < 3.0, f"Took {elapsed:.2f}s"

        page.close()
        browser.close()


def test_rapid_date_switching() -> None:
    """Rapidly switching dates should not hang."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        frames = collect_ws_frames(page)

        page.goto(f"{BASE_URL}/?symbol=SPX&interval=m")
        wait_for_init(frames, page)

        dates = ["2026-03-31", "2026-03-28", "2026-04-01", "2026-03-31"]
        start = time.monotonic()

        for date in dates:
            frames.clear()
            change_date(page, date)
            init_msg = wait_for_init(frames, page, timeout=10.0)
            assert init_msg is not None, f"Date {date} did not load"

        elapsed = time.monotonic() - start
        print(f"  PASS: {len(dates)} date switches in {elapsed:.2f}s")
        assert elapsed < 20.0, f"Took {elapsed:.2f}s"

        page.close()
        browser.close()


def test_disconnect_cleanup() -> None:
    """New connection after disconnect should not be delayed."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page1 = browser.new_page()
        frames1 = collect_ws_frames(page1)
        page1.goto(f"{BASE_URL}/?symbol=SPX&interval=m")
        wait_for_init(frames1, page1)

        start = time.monotonic()
        page1.close()

        page2 = browser.new_page()
        frames2 = collect_ws_frames(page2)
        page2.goto(f"{BASE_URL}/?symbol=SPX&interval=m")
        init_msg = wait_for_init(frames2, page2)
        elapsed = time.monotonic() - start

        assert init_msg is not None, "Reconnect did not complete"
        print(f"  PASS: Reconnect in {elapsed:.2f}s")
        assert elapsed < 5.0, f"Took {elapsed:.2f}s"

        page2.close()
        browser.close()
