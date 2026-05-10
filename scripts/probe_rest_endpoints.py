"""Probe Tastytrade REST endpoints for SPX 0DTE option fields.

Walks /option-chains/SPX/nested, /market-data/by-type, and /market-metrics
to determine which fields (gamma, delta, OI, IV) are actually returned.

Read-only. No subscriptions, no orders.
"""

import asyncio
import json
import sys
from datetime import date

from tastytrade.config.manager import RedisConfigManager
from tastytrade.connections import Credentials
from tastytrade.connections.requests import AsyncSessionHandler


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


async def main() -> int:
    config = RedisConfigManager()
    creds = Credentials(config, env="Live")
    handler = await AsyncSessionHandler.create(creds)
    sess = handler.session
    base = creds.base_url

    today = date.today().isoformat()
    print(f"Probing REST endpoints for SPX, expiry={today}")

    # 1. Chain
    header("1. GET /option-chains/SPX/nested  (structure only)")
    async with sess.get(f"{base}/option-chains/SPX/nested") as r:
        chain = await r.json()
    items = chain["data"]["items"]
    print(f"roots returned: {[i['root-symbol'] for i in items]}")
    print(f"top-level keys for root[0]: {list(items[0].keys())}")
    print(f"expiration[0] keys: {list(items[0]['expirations'][0].keys())}")
    print(f"strike[0] keys: {list(items[0]['expirations'][0]['strikes'][0].keys())}")

    today_expiries = []
    for root in items:
        for exp in root["expirations"]:
            if exp["expiration-date"] == today:
                today_expiries.append((root["root-symbol"], exp))
    print(
        f"\n0DTE expirations found: {[(r, e['expiration-date']) for r, e in today_expiries]}"
    )

    if not today_expiries:
        print("\nNo 0DTE — using nearest expiration instead.")
        nearest = min(
            (
                (root["root-symbol"], exp)
                for root in items
                for exp in root["expirations"]
            ),
            key=lambda re: re[1]["expiration-date"],
        )
        today_expiries = [nearest]

    root_sym, exp = today_expiries[0]
    print(
        f"Using {root_sym} {exp['expiration-date']}, " f"{len(exp['strikes'])} strikes"
    )

    sample = exp["strikes"][len(exp["strikes"]) // 2]
    print(f"Sample mid-chain strike entry: {json.dumps(sample, indent=2)}")

    # Pick 3 strikes for the probe
    mids = exp["strikes"][len(exp["strikes"]) // 2 - 1 : len(exp["strikes"]) // 2 + 2]
    call_syms = [s["call"] for s in mids]
    put_syms = [s["put"] for s in mids]
    print(f"\nProbe symbols (occ): {call_syms + put_syms}")

    # 2. /market-data/by-type for index (SPX spot)
    header("2. GET /market-data/by-type?index=SPX  (spot)")
    async with sess.get(f"{base}/market-data/by-type", params={"index": "SPX"}) as r:
        spx_md = await r.json()
    show_keys(spx_md["data"]["items"][0])

    # 3. /market-data/by-type for equity-option (the key probe)
    header("3. GET /market-data/by-type?equity-option=...  (option fields!)")
    params = {"equity-option": ",".join(call_syms[:1] + put_syms[:1])}
    async with sess.get(f"{base}/market-data/by-type", params=params) as r:
        opt_md = await r.json()
    print(f"HTTP {r.status}")
    print(json.dumps(opt_md, indent=2))

    # 4. Market metrics for SPX (underlying-level)
    header("4. GET /market-metrics?symbols=SPX  (underlying metrics)")
    async with sess.get(f"{base}/market-metrics", params={"symbols": "SPX"}) as r:
        mm = await r.json()
    if mm.get("data", {}).get("items"):
        show_keys(mm["data"]["items"][0])
    else:
        print(json.dumps(mm, indent=2))

    # 5. Per-instrument equity-option lookup
    header("5. GET /instruments/equity-options/{sym}  (instrument metadata)")
    async with sess.get(f"{base}/instruments/equity-options/{call_syms[0]}") as r:
        inst = await r.json()
    show_keys(inst.get("data", inst))

    await sess.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
