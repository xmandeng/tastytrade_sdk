"""Tests for the unified option chain fetcher."""

from typing import Any

import polars as pl
import pytest

from tastytrade.market.option_chains import (
    fetch_equity_chain,
    fetch_futures_chain,
    filter_by_dte,
    futures_product_code,
    get_option_chain,
    is_futures_symbol,
)


# ---------------------------------------------------------------------------
# Mock session
# ---------------------------------------------------------------------------


class MockResponse:
    """Simulates an aiohttp response context manager."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def json(self) -> dict[str, Any]:
        return self._data

    async def __aenter__(self) -> "MockResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class MockHttpSession:
    """Simulates aiohttp.ClientSession.get()."""

    def __init__(self) -> None:
        self._response_data: dict[str, Any] = {}
        self.last_url: str = ""

    def set_response(self, data: dict[str, Any]) -> None:
        self._response_data = data

    def get(self, url: str, **kwargs: object) -> MockResponse:
        self.last_url = url
        return MockResponse(self._response_data)


class MockSession:
    """Simulates AsyncSessionHandler with a mock HTTP session."""

    def __init__(self) -> None:
        self.base_url = "https://api.tastyworks.com"
        self.session = MockHttpSession()

    def set_response(self, data: dict[str, Any]) -> None:
        self.session.set_response(data)


@pytest.fixture
def mock_session() -> MockSession:
    return MockSession()


# ---------------------------------------------------------------------------
# Symbol detection
# ---------------------------------------------------------------------------


class TestSymbolDetection:
    def test_futures_symbol_with_slash(self) -> None:
        assert is_futures_symbol("/GC") is True
        assert is_futures_symbol("/ES") is True
        assert is_futures_symbol("/CL") is True

    def test_equity_symbol_without_slash(self) -> None:
        assert is_futures_symbol("SPX") is False
        assert is_futures_symbol("CSCO") is False
        assert is_futures_symbol("XLE") is False

    def test_product_code_extraction(self) -> None:
        assert futures_product_code("/GC") == "GC"
        assert futures_product_code("/ES") == "ES"
        assert futures_product_code("GC") == "GC"


# ---------------------------------------------------------------------------
# DTE filtering
# ---------------------------------------------------------------------------


class TestDteFiltering:
    @pytest.fixture
    def chain_df(self) -> pl.DataFrame:
        """DataFrame with DTEs at 0, 2, 7, 30, 45, 90."""
        rows = []
        for dte in [0, 2, 7, 30, 45, 90]:
            rows.append(
                {
                    "underlying": "SPX",
                    "root": "SPXW",
                    "expiration": f"2026-01-{dte + 1:02d}",
                    "expiration_type": "Weekly",
                    "settlement": "PM",
                    "dte": dte,
                    "strike": 5700.0,
                    "shares_per_contract": 100,
                    "option_type": "C",
                    "symbol": "SPXW  260101C05700000",
                    "streamer_symbol": ".SPXW260101C5700",
                }
            )
        return pl.DataFrame(rows)

    def test_exact_match(self, chain_df: pl.DataFrame) -> None:
        result = filter_by_dte(chain_df, [30])
        assert result["dte"].unique().to_list() == [30]

    def test_closest_match(self, chain_df: pl.DataFrame) -> None:
        result = filter_by_dte(chain_df, [28])
        assert result["dte"].unique().to_list() == [30]

    def test_multiple_targets(self, chain_df: pl.DataFrame) -> None:
        result = filter_by_dte(chain_df, [0, 30, 45])
        matched = sorted(result["dte"].unique().to_list())
        assert matched == [0, 30, 45]

    def test_target_between_dtes(self, chain_df: pl.DataFrame) -> None:
        # 5 is equidistant from 2 and 7; min() picks 2
        result = filter_by_dte(chain_df, [5])
        matched = result["dte"].unique().to_list()
        assert matched == [2] or matched == [7]

    def test_empty_dataframe(self) -> None:
        empty = pl.DataFrame()
        result = filter_by_dte(empty, [30])
        assert result.is_empty()

    def test_no_target_dtes(self, chain_df: pl.DataFrame) -> None:
        result = filter_by_dte(chain_df, [])
        assert result.shape == chain_df.shape

    def test_deduplicates_matched_dtes(self, chain_df: pl.DataFrame) -> None:
        # Both 29 and 31 should match to DTE 30
        result = filter_by_dte(chain_df, [29, 31])
        matched = result["dte"].unique().to_list()
        assert matched == [30]


# ---------------------------------------------------------------------------
# Equity chain parsing
# ---------------------------------------------------------------------------

EQUITY_NESTED_RESPONSE: dict[str, Any] = {
    "data": {
        "items": [
            {
                "underlying-symbol": "SPX",
                "root-symbol": "SPX",
                "option-chain-type": "Standard",
                "shares-per-contract": 100,
                "expirations": [
                    {
                        "expiration-type": "Regular",
                        "expiration-date": "2026-03-20",
                        "days-to-expiration": 2,
                        "settlement-type": "AM",
                        "strikes": [
                            {
                                "strike-price": "5700.0",
                                "call": "SPX   260320C05700000",
                                "call-streamer-symbol": ".SPX260320C5700",
                                "put": "SPX   260320P05700000",
                                "put-streamer-symbol": ".SPX260320P5700",
                            }
                        ],
                    }
                ],
            },
            {
                "underlying-symbol": "SPX",
                "root-symbol": "SPXW",
                "option-chain-type": "Standard",
                "shares-per-contract": 100,
                "expirations": [
                    {
                        "expiration-type": "Weekly",
                        "expiration-date": "2026-03-18",
                        "days-to-expiration": 0,
                        "settlement-type": "PM",
                        "strikes": [
                            {
                                "strike-price": "5700.0",
                                "call": "SPXW  260318C05700000",
                                "call-streamer-symbol": ".SPXW260318C5700",
                                "put": "SPXW  260318P05700000",
                                "put-streamer-symbol": ".SPXW260318P5700",
                            },
                            {
                                "strike-price": "5750.0",
                                "call": "SPXW  260318C05750000",
                                "call-streamer-symbol": ".SPXW260318C5750",
                                "put": "SPXW  260318P05750000",
                                "put-streamer-symbol": ".SPXW260318P5750",
                            },
                        ],
                    }
                ],
            },
        ]
    }
}


class TestEquityChainParsing:
    @pytest.mark.asyncio
    async def test_row_count(self, mock_session: MockSession) -> None:
        mock_session.set_response(EQUITY_NESTED_RESPONSE)
        df = await fetch_equity_chain(mock_session, "SPX")  # type: ignore[arg-type]
        # 1 strike (call+put) from SPX + 2 strikes (call+put) from SPXW = 6
        assert df.shape[0] == 6

    @pytest.mark.asyncio
    async def test_multiple_roots(self, mock_session: MockSession) -> None:
        mock_session.set_response(EQUITY_NESTED_RESPONSE)
        df = await fetch_equity_chain(mock_session, "SPX")  # type: ignore[arg-type]
        roots = sorted(df["root"].unique().to_list())
        assert roots == ["SPX", "SPXW"]

    @pytest.mark.asyncio
    async def test_columns(self, mock_session: MockSession) -> None:
        mock_session.set_response(EQUITY_NESTED_RESPONSE)
        df = await fetch_equity_chain(mock_session, "SPX")  # type: ignore[arg-type]
        expected = {
            "underlying",
            "root",
            "expiration",
            "expiration_type",
            "settlement",
            "dte",
            "strike",
            "shares_per_contract",
            "option_type",
            "symbol",
            "streamer_symbol",
        }
        assert set(df.columns) == expected

    @pytest.mark.asyncio
    async def test_option_types(self, mock_session: MockSession) -> None:
        mock_session.set_response(EQUITY_NESTED_RESPONSE)
        df = await fetch_equity_chain(mock_session, "SPX")  # type: ignore[arg-type]
        types = sorted(df["option_type"].unique().to_list())
        assert types == ["C", "P"]

    @pytest.mark.asyncio
    async def test_empty_response(self, mock_session: MockSession) -> None:
        mock_session.set_response({"data": {"items": []}})
        df = await fetch_equity_chain(mock_session, "INVALID")  # type: ignore[arg-type]
        assert df.is_empty()


# ---------------------------------------------------------------------------
# Futures chain parsing
# ---------------------------------------------------------------------------

FUTURES_FLAT_RESPONSE: dict[str, Any] = {
    "data": {
        "items": [
            {
                "underlying-symbol": "/GCM6",
                "root-symbol": "/GC",
                "expiration-date": "2026-04-28",
                "strike-price": "3000.0",
                "option-type": "C",
                "days-to-expiration": 40,
                "symbol": "./GCM6 OGK6  260428C3000",
                "streamer-symbol": "./OGK26C3000:XCEC",
                "settlement-type": "Future",
                "option-root-symbol": "OG",
                "product-code": "GC",
                "exchange": "CME",
                "future-option-product": {
                    "expiration-type": "Regular",
                },
            },
            {
                "underlying-symbol": "/GCM6",
                "root-symbol": "/GC",
                "expiration-date": "2026-04-28",
                "strike-price": "3000.0",
                "option-type": "P",
                "days-to-expiration": 40,
                "symbol": "./GCM6 OGK6  260428P3000",
                "streamer-symbol": "./OGK26P3000:XCEC",
                "settlement-type": "Future",
                "option-root-symbol": "OG",
                "product-code": "GC",
                "exchange": "CME",
                "future-option-product": {
                    "expiration-type": "Regular",
                },
            },
            {
                "underlying-symbol": "/GCJ6",
                "root-symbol": "/GC",
                "expiration-date": "2026-03-26",
                "strike-price": "2950.0",
                "option-type": "C",
                "days-to-expiration": 8,
                "symbol": "./GCJ6 OGJ6  260326C2950",
                "streamer-symbol": "./OGJ26C2950:XCEC",
                "settlement-type": "Future",
                "option-root-symbol": "OG",
                "product-code": "GC",
                "exchange": "CME",
                "future-option-product": {
                    "expiration-type": "Regular",
                },
            },
        ]
    }
}


class TestFuturesChainParsing:
    @pytest.mark.asyncio
    async def test_row_count(self, mock_session: MockSession) -> None:
        mock_session.set_response(FUTURES_FLAT_RESPONSE)
        df = await fetch_futures_chain(mock_session, "/GC")  # type: ignore[arg-type]
        assert df.shape[0] == 3

    @pytest.mark.asyncio
    async def test_multiple_underlyings(self, mock_session: MockSession) -> None:
        mock_session.set_response(FUTURES_FLAT_RESPONSE)
        df = await fetch_futures_chain(mock_session, "/GC")  # type: ignore[arg-type]
        underlyings = sorted(df["underlying"].unique().to_list())
        assert underlyings == ["/GCJ6", "/GCM6"]

    @pytest.mark.asyncio
    async def test_futures_columns(self, mock_session: MockSession) -> None:
        mock_session.set_response(FUTURES_FLAT_RESPONSE)
        df = await fetch_futures_chain(mock_session, "/GC")  # type: ignore[arg-type]
        assert "option_root" in df.columns
        assert "product_code" in df.columns
        assert "exchange" in df.columns

    @pytest.mark.asyncio
    async def test_empty_response(self, mock_session: MockSession) -> None:
        mock_session.set_response({"data": {"items": []}})
        df = await fetch_futures_chain(mock_session, "/ZZ")  # type: ignore[arg-type]
        assert df.is_empty()


# ---------------------------------------------------------------------------
# Unified get_option_chain
# ---------------------------------------------------------------------------


class TestGetOptionChain:
    @pytest.mark.asyncio
    async def test_routes_equity(self, mock_session: MockSession) -> None:
        mock_session.set_response(EQUITY_NESTED_RESPONSE)
        df = await get_option_chain(mock_session, "SPX")  # type: ignore[arg-type]
        assert not df.is_empty()
        assert mock_session.session.last_url.endswith("/option-chains/SPX/nested")

    @pytest.mark.asyncio
    async def test_routes_futures(self, mock_session: MockSession) -> None:
        mock_session.set_response(FUTURES_FLAT_RESPONSE)
        df = await get_option_chain(mock_session, "/GC")  # type: ignore[arg-type]
        assert not df.is_empty()
        assert mock_session.session.last_url.endswith("/futures-option-chains/GC")

    @pytest.mark.asyncio
    async def test_with_dte_filter(self, mock_session: MockSession) -> None:
        mock_session.set_response(EQUITY_NESTED_RESPONSE)
        df = await get_option_chain(mock_session, "SPX", target_dtes=[0])  # type: ignore[arg-type]
        # Only SPXW DTE=0 should remain
        assert all(df["dte"] == 0)
