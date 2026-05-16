"""Deep probe for futures-options points 3, 4, 5 from the §6.13 follow-up.

Investigates:
  (3) Symbol-format anatomy — break down `./MESM6X3AK6 260518C7690` into its pieces
  (4) Multiplier source — which field on the expiration carries the contract multiplier?
      Candidates: notional-value, display-factor, value-of-1-pt
  (5) Instrument-metadata endpoint — find the working path. Try several variants of
      /instruments/future-options/<sym> with different encodings.

Read-only.
"""

import asyncio
import sys
import urllib.parse
from datetime import date

from tastytrade.config.manager import RedisConfigManager
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler

PRODUCTS = ["/MES", "/ES"]


def header(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def show_field(label: str, value: object) -> None:
    print(f"  {label:<24}: {value}")


async def probe_one(sess, base: str, root: str) -> None:
    header(f"FUTURES ROOT: {root}")

    root_path = root.lstrip("/")
    chain_url = f"{base}/futures-option-chains/{root_path}/nested"
    print(f"\n[chain] GET {chain_url}")
    async with sess.get(chain_url) as r:
        if r.status != 200:
            print(f"  HTTP {r.status}")
            return
        chain = await r.json()

    option_chains = chain.get("data", {}).get("option-chains", [])
    if not option_chains:
        print("  No option-chains in response")
        return

    first = option_chains[0]
    expirations = first.get("expirations", [])
    if not expirations:
        return

    nearest = min(expirations, key=lambda e: e.get("expiration-date", "9999-12-31"))

    # =====================================================================
    # (4) Multiplier source — print all candidate fields from the expiration
    # =====================================================================
    print(
        f"\n[4] Multiplier candidate fields on the expiration "
        f"({nearest['expiration-date']}):"
    )
    for k in [
        "underlying-symbol",
        "option-root-symbol",
        "option-contract-symbol",
        "asset",
        "expiration-type",
        "settlement-type",
        "notional-value",
        "display-factor",
        "strike-factor",
        "stops-trading-at",
        "expires-at",
    ]:
        if k in nearest:
            show_field(k, nearest[k])

    print("\n  (chain-level fields:)")
    for k in ["exercise-style", "underlying-symbol", "root-symbol"]:
        if k in first:
            show_field(k, first[k])

    strikes = nearest.get("strikes", [])
    if not strikes:
        return

    # Pick a strike close to spot — use the lowest-priced put for a near-ATM pick
    # (We don't have spot in the chain, so just pick a mid-chain strike as proxy.)
    mid = strikes[len(strikes) // 2]
    call_sym = mid["call"]
    put_sym = mid["put"]
    strike = mid["strike-price"]
    print(f"\n  Sample mid-strike: {strike}")
    print(f"  Sample call OCC: {call_sym!r}")
    print(f"  Sample put  OCC: {put_sym!r}")
    print(f"  Sample call streamer: {mid['call-streamer-symbol']!r}")
    print(f"  Sample put  streamer: {mid['put-streamer-symbol']!r}")

    # =====================================================================
    # (3) Symbol-format anatomy — try to decompose `./MESM6X3AK6 260518C7690`
    # =====================================================================
    print(f"\n[3] Symbol decomposition for {call_sym!r}:")
    s = call_sym
    if s.startswith("."):
        print("  Prefix '.' indicates futures option (vs leading letter for equity).")
    parts = s.split(" ")
    print(f"  Whitespace-split parts: {parts}")
    if len(parts) >= 2:
        head = parts[0]  # e.g. "./MESM6X3AK6"
        tail = parts[-1]  # e.g. "260518C7690"
        print(f"    head (futures + series): {head!r}")
        print(f"    tail (expiry+CP+strike): {tail!r}")
        if len(tail) >= 7:
            yymmdd = tail[:6]
            cp = tail[6]
            strike_part = tail[7:] if len(tail) > 7 else ""
            print(f"      expiration YYMMDD: {yymmdd}")
            print(f"      C/P flag         : {cp}")
            print(f"      strike (raw)     : {strike_part}")
    print(f"  Underlying futures symbol (chain): {nearest.get('underlying-symbol')}")
    print(f"  Option root symbol (chain)      : {nearest.get('option-root-symbol')}")
    print(
        f"  Option contract symbol (chain)  : {nearest.get('option-contract-symbol')}"
    )

    # =====================================================================
    # Market data — pull just to compare with point-value math
    # =====================================================================
    md_url = f"{base}/market-data/by-type"
    print(f"\n[md] GET {md_url}?future-option={call_sym}")
    async with sess.get(md_url, params={"future-option": call_sym}) as r:
        if r.status != 200:
            print(f"  HTTP {r.status}")
            return
        md = await r.json()
    items = md.get("data", {}).get("items", [])
    if not items:
        return
    item = items[0]
    gamma = item.get("gamma")
    oi = item.get("open-interest")
    mark = item.get("mark")
    print(f"  gamma={gamma} OI={oi} mark={mark}")

    # Try to compute an expected GEX assuming notional-value is the multiplier
    notional = nearest.get("notional-value")
    display_factor = nearest.get("display-factor")
    try:
        notional_f = float(notional) if notional is not None else None
    except (TypeError, ValueError):
        notional_f = None
    if gamma is not None and oi is not None and notional_f is not None:
        # Spot proxy: use mark of an ITM call as a rough underlying proxy isn't great;
        # just demonstrate the math with a stand-in spot. The point is to show what
        # the multiplier factor needs to be.
        print("\n  GEX-multiplier math demonstration:")
        print(f"    notional-value  = {notional!r}  (={notional_f})")
        print(f"    display-factor  = {display_factor!r}")
        print("    For equity-option GEX, multiplier = 100 (shares per contract).")
        print(
            "    For futures-option GEX, multiplier = notional-per-point of the future."
        )
        print(
            "    /MES = $5/pt; /ES = $50/pt — read from notional-value or "
            "the future-product 'value-of-1-pt' field."
        )

    # =====================================================================
    # (5) Instrument-metadata endpoint — try several variants
    # =====================================================================
    print(f"\n[5] Probing instrument-metadata endpoint variants for {call_sym!r}:")
    variants = [
        (
            "future-options/<sym>",
            f"{base}/instruments/future-options/{urllib.parse.quote(call_sym, safe='')}",
        ),
        ("future-options (raw path)", f"{base}/instruments/future-options/{call_sym}"),
        (
            "future-options?symbol=",
            f"{base}/instruments/future-options?symbol={urllib.parse.quote(call_sym, safe='')}",
        ),
        # The futures (not future-options) endpoint might cover the *underlying* future
        (
            "futures/<MESM6>",
            f"{base}/instruments/futures/{nearest.get('underlying-symbol','').lstrip('/')}",
        ),
        ("future-option-products", f"{base}/instruments/future-option-products"),
    ]
    for label, url in variants:
        async with sess.get(url) as r:
            print(f"  [{r.status:3d}] {label:<30}  {url}")
            if r.status == 200:
                body = await r.json()
                data = body.get("data", body)
                # If 'items' is in data, show first; else show top-level keys
                if isinstance(data, dict) and "items" in data and data["items"]:
                    first_item = data["items"][0]
                    keys = (
                        list(first_item.keys()) if isinstance(first_item, dict) else []
                    )
                    print(f"      items[0] keys ({len(keys)}): {keys[:20]}")
                elif isinstance(data, dict):
                    print(f"      data keys: {list(data.keys())[:20]}")


async def main() -> int:
    config = RedisConfigManager()
    creds = Credentials(config, env="Live")
    handler = await AsyncSessionHandler.create(creds)
    sess = handler.session
    base = creds.base_url

    print(f"Deep probe @ {date.today().isoformat()}")
    print(f"Roots: {PRODUCTS}")
    for root in PRODUCTS:
        try:
            await probe_one(sess, base, root)
        except Exception as e:
            print(f"\n!! Exception on {root}: {e!r}")

    await sess.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
