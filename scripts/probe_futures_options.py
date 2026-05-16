"""Probe Tastytrade REST endpoints for futures-options field availability.

Resolves plan §6.13 — extends the equity-option probe to walk:
  GET /futures-option-chains/<root>/nested
  GET /market-data/by-type?future-option=<sym>
  GET /instruments/future-options/<sym>  (metadata)

Goal: confirm whether `future-option=` returns the same field set as
`equity-option=` (gamma, delta, OI, IV, theo-price) so we know if the
GEX architecture can extend to futures-options later. Implementation
is out of v1 scope per plan §6.13 — only field-availability is checked.

Read-only. No subscriptions, no orders.
"""

import asyncio
import json
import sys
from datetime import date

from tastytrade.config.manager import RedisConfigManager
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler

# Liquid futures-options products worth probing
PRODUCTS = ["/MES", "/ES"]


def header(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def show_keys(obj: object, indent: int = 0) -> None:
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"{pad}{k}:")
                show_keys(v, indent + 1)
            else:
                print(f"{pad}{k}: {v}")
    elif isinstance(obj, list) and obj:
        print(f"{pad}[list len={len(obj)}, sample item:]")
        show_keys(obj[0], indent + 1)


async def probe_root(sess, base: str, root: str) -> dict | None:
    """Walk one futures root through chain → market-data → instrument metadata.

    Returns a dict summarizing whether key fields landed, or None if the
    root produced no chain.
    """
    header(f"FUTURES ROOT: {root}")

    # 1. Chain — strip leading slash from root for the URL path
    root_path = root.lstrip("/")
    chain_url = f"{base}/futures-option-chains/{root_path}/nested"
    print(f"\n[1] GET {chain_url}")
    async with sess.get(chain_url) as r:
        if r.status != 200:
            print(f"  HTTP {r.status} — root {root} not available")
            return None
        chain = await r.json()

    # Real shape: data.option-chains[].expirations[].strikes[]
    option_chains = chain.get("data", {}).get("option-chains", [])
    if not option_chains:
        print(
            f"  Unexpected response shape. Top-level keys: {list(chain.get('data', {}).keys())}"
        )
        return None

    first = option_chains[0]
    print(f"  Returned {len(option_chains)} chain(s) for {root}")
    print(f"  Top-level keys: {list(first.keys())}")

    expirations = first.get("expirations", [])
    if not expirations:
        print("  No expirations in chain — skipping")
        return None
    print(f"  {len(expirations)} expirations available")
    print(f"  expiration[0] keys: {list(expirations[0].keys())}")

    # Pick nearest expiration
    nearest = min(expirations, key=lambda e: e.get("expiration-date", "9999-12-31"))
    print(
        f"\n  Nearest expiration: {nearest.get('expiration-date')} "
        f"(DTE field: {nearest.get('days-to-expiration')})"
    )

    strikes = nearest.get("strikes", [])
    if not strikes:
        print("  No strikes in nearest expiration")
        return None

    print(f"  {len(strikes)} strikes. strike[0] keys: {list(strikes[0].keys())}")

    # Pick middle strike for the field probe
    mid = strikes[len(strikes) // 2]
    print("\n  Sample mid-chain strike entry:")
    print(json.dumps(mid, indent=4))

    call_sym = mid.get("call")
    if not call_sym:
        print("  Mid strike has no call symbol")
        return None

    # 2. Market data
    md_url = f"{base}/market-data/by-type"
    print(f"\n[2] GET {md_url}?future-option={call_sym}")
    async with sess.get(md_url, params={"future-option": call_sym}) as r:
        print(f"  HTTP {r.status}")
        md = await r.json()

    items = md.get("data", {}).get("items", [])
    if not items:
        print(f"  No items returned. Body: {json.dumps(md, indent=2)[:500]}")
        return None

    item = items[0]
    print(f"\n  Returned field names ({len(item)}):")
    for k in sorted(item.keys()):
        v = item[k]
        v_repr = (
            repr(v)
            if v is None
            else (str(v)[:60] if not isinstance(v, (dict, list)) else "...")
        )
        print(f"    {k}: {v_repr}")

    # Field-availability summary
    targets = [
        "gamma",
        "delta",
        "theta",
        "vega",
        "rho",
        "volatility",
        "theo-price",
        "dx-mark",
        "open-interest",
        "bid",
        "ask",
        "mark",
    ]
    summary = {f: (f in item and item[f] is not None) for f in targets}

    print("\n  Field-availability summary (target → present-and-non-null):")
    for f, present in summary.items():
        marker = "✓" if present else "✗"
        val = item.get(f, "<absent>") if present else item.get(f, "<absent>")
        print(f"    {marker} {f}: {val}")

    # 3. Instrument metadata (which multiplier?)
    inst_url = f"{base}/instruments/future-options/{call_sym}"
    print(f"\n[3] GET {inst_url}")
    async with sess.get(inst_url) as r:
        print(f"  HTTP {r.status}")
        if r.status == 200:
            inst = await r.json()
            inst_data = inst.get("data", inst)
            print("  Selected instrument fields:")
            for k in [
                "symbol",
                "underlying-symbol",
                "product-code",
                "exchange",
                "expiration-date",
                "strike-price",
                "option-type",
                "exercise-style",
                "settlement-type",
                "notional-value",
                "display-factor",
                "value-of-1-pt",
            ]:
                if k in inst_data:
                    print(f"    {k}: {inst_data[k]}")
            # Print remaining keys at a glance
            other_keys = [
                k
                for k in inst_data.keys()
                if k
                not in {
                    "symbol",
                    "underlying-symbol",
                    "product-code",
                    "exchange",
                    "expiration-date",
                    "strike-price",
                    "option-type",
                    "exercise-style",
                    "settlement-type",
                    "notional-value",
                    "display-factor",
                    "value-of-1-pt",
                }
            ]
            print(f"    (other keys: {other_keys})")

    return {"root": root, "fields_present": summary, "symbol": call_sym}


async def main() -> int:
    config = RedisConfigManager()
    creds = Credentials(config, env="Live")
    handler = await AsyncSessionHandler.create(creds)
    sess = handler.session
    base = creds.base_url

    print(f"Probing futures-options REST endpoints. base={base}")
    print(f"Today: {date.today().isoformat()}")
    print(f"Roots to probe: {PRODUCTS}")

    summaries = []
    for root in PRODUCTS:
        try:
            s = await probe_root(sess, base, root)
            if s:
                summaries.append(s)
        except Exception as e:
            print(f"\n!! Exception probing {root}: {e!r}")

    header("CROSS-ROOT SUMMARY")
    target_fields = [
        "gamma",
        "delta",
        "open-interest",
        "volatility",
        "theo-price",
        "mark",
        "bid",
        "ask",
    ]
    print(f"{'field':<14} | " + " | ".join(f"{s['root']:<8}" for s in summaries))
    print("-" * (16 + 11 * len(summaries)))
    for f in target_fields:
        row = f"{f:<14} | " + " | ".join(
            ("✓" if s["fields_present"].get(f) else "✗").ljust(8) for s in summaries
        )
        print(row)

    await sess.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
