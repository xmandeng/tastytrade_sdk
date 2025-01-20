from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Optional

from tastytrade.sessions.requests import AsyncSessionHandler


@dataclass
class OptionChainRequest:
    symbol: str
    expiration_date: Optional[date] = None
    strikes_by_delta: Optional[float] = None  # e.g. 0.10 for 10 delta
    strikes_by_price: Optional[float] = None  # e.g. 5.0 for $5 strikes


class OptionsClient:
    def __init__(self, session: "AsyncSessionHandler"):  # type: ignore
        self.session = session

    async def get_chains(self, request: OptionChainRequest) -> Dict[str, Any]:
        """Get option chains with optional filtering."""
        params = {}
        if request.expiration_date:
            params["expiration"] = request.expiration_date.strftime("%Y-%m-%d")
        if request.strikes_by_delta:
            params["strikes-by-delta"] = str(request.strikes_by_delta)
        if request.strikes_by_price:
            params["strikes-by-price"] = str(request.strikes_by_price)

        async with self.session.session.get(
            f"{self.session.base_url}/option-chains/{request.symbol}", params=params
        ) as response:
            data = await response.json()
            return data
