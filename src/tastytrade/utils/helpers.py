import re
from typing import Optional


def format_candle_symbol(symbol: str) -> str:
    """Extract time interval from symbol."""
    return re.sub(r"(?<=\{=)1([a-zA-Z])(?=\})", lambda m: f"{m.group(1)}", symbol)


def parse_candle_symbol(symbol: str) -> tuple[Optional[str], Optional[str]]:
    match = re.match(r"([a-zA-Z0-9\/:]+)\{=(\d*[a-zA-Z])\}", symbol)

    if match is None:
        return None, None

    ticker = match.group(1)
    interval = match.group(2) if len(match.group(2)) > 1 else "1" + match.group(2)

    return ticker, interval
