"""
Tests for the NSE Index Constituent Service.

Covers:
  - Index name mapping and validation
  - Response parsing (constituents, weightage)
  - Caching behavior
  - Session management and error handling
  - Rate limiting
  - Fallback/error paths
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.nse_index import (
    AVAILABLE_INDICES,
    INDEX_URL_NAMES,
    IndexConstituent,
    IndexData,
    NSEIndexError,
    NSEIndexService,
)


# ── Sample API Response Data ──────────────────────────────────────────────


def _make_nse_response(index_name: str = "NIFTY 50", stocks: list[dict] | None = None):
    """Create a sample NSE API response for testing."""
    if stocks is None:
        stocks = [
            {
                "symbol": "RELIANCE",
                "lastPrice": 2500.0,
                "change": 25.0,
                "pChange": 1.01,
                "ffmc": 1700000.0,
                "priority": 0,
                "meta": {
                    "companyName": "Reliance Industries",
                    "isin": "INE002A01018",
                    "industry": "Oil & Gas",
                    "isFNOSec": True,
                    "series": "EQ",
                },
            },
            {
                "symbol": "TCS",
                "lastPrice": 3500.0,
                "change": -10.0,
                "pChange": -0.28,
                "ffmc": 1200000.0,
                "priority": 0,
                "meta": {
                    "companyName": "Tata Consultancy Services",
                    "isin": "INE467B01029",
                    "industry": "IT Services",
                    "isFNOSec": True,
                    "series": "EQ",
                },
            },
            {
                "symbol": "INFY",
                "lastPrice": 1800.0,
                "change": 5.0,
                "pChange": 0.28,
                "ffmc": 800000.0,
                "priority": 0,
                "meta": {
                    "companyName": "Infosys",
                    "isin": "INE009A01021",
                    "industry": "IT Services",
                    "isFNOSec": True,
                    "series": "EQ",
                },
            },
        ]

    return {
        "data": [
            {
                "symbol": index_name,
                "lastPrice": 22500.0,
                "change": 150.0,
                "pChange": 0.67,
                "priority": 1,
            },
            *stocks,
        ],
        "metadata": {
            "indexName": index_name,
        },
    }


# ═══════════════════════════════════════════════════════════════
#  Index Name Mapping
# ═══════════════════════════════════════════════════════════════


class TestIndexNameMapping:
    def test_has_16_indices(self):
        assert len(INDEX_URL_NAMES) == 16

    def test_available_indices_matches_keys(self):
        assert AVAILABLE_INDICES == list(INDEX_URL_NAMES.keys())

    def test_all_expected_indices_present(self):
        expected = [
            "NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY FIN SERVICE",
            "NIFTY PHARMA", "NIFTY AUTO", "NIFTY METAL", "NIFTY ENERGY",
            "NIFTY FMCG", "NIFTY REALTY", "NIFTY INFRA", "NIFTY PSU BANK",
            "NIFTY MEDIA", "NIFTY MIDCAP 50", "NIFTY MIDCAP 100", "NIFTY MID SELECT",
        ]
        for name in expected:
            assert name in INDEX_URL_NAMES, f"Missing index: {name}"

    def test_nifty_fin_service_url_differs(self):
        """NIFTY FIN SERVICE uses 'NIFTY FINANCIAL SERVICES' in URL."""
        assert INDEX_URL_NAMES["NIFTY FIN SERVICE"] == "NIFTY FINANCIAL SERVICES"

    def test_most_indices_url_matches_key(self):
        """Most indices use the same name in URL as in key."""
        for key, url_name in INDEX_URL_NAMES.items():
            if key != "NIFTY FIN SERVICE":
                assert key == url_name, f"{key} should use same URL name"


# ═══════════════════════════════════════════════════════════════
#  IndexConstituent / IndexData
# ═══════════════════════════════════════════════════════════════


class TestIndexData:
    def test_symbols_property(self):
        constituents = [
            IndexConstituent(
                symbol="RELIANCE", company_name="Reliance", isin="INE002A01018",
                industry="Oil", last_price=2500.0, change=10.0, change_pct=0.4,
                ffmc=1700000.0, is_fno=True, series="EQ",
            ),
            IndexConstituent(
                symbol="TCS", company_name="TCS", isin="INE467B01029",
                industry="IT", last_price=3500.0, change=-5.0, change_pct=-0.14,
                ffmc=1200000.0, is_fno=True, series="EQ",
            ),
        ]
        data = IndexData(
            index_name="NIFTY 50", last_price=22000.0, change=100.0,
            change_pct=0.45, constituents=constituents,
        )
        assert data.symbols == ["RELIANCE", "TCS"]
        assert data.constituent_count == 2

    def test_get_weightages(self):
        constituents = [
            IndexConstituent(
                symbol="A", company_name="A", isin="", industry="",
                last_price=100.0, change=0.0, change_pct=0.0,
                ffmc=750.0, is_fno=False, series="EQ",
            ),
            IndexConstituent(
                symbol="B", company_name="B", isin="", industry="",
                last_price=200.0, change=0.0, change_pct=0.0,
                ffmc=250.0, is_fno=False, series="EQ",
            ),
        ]
        data = IndexData(
            index_name="TEST", last_price=0, change=0, change_pct=0,
            constituents=constituents,
        )
        weights = data.get_weightages()
        assert weights["A"] == 75.0
        assert weights["B"] == 25.0

    def test_get_weightages_zero_ffmc(self):
        """If all ffmc is 0, weightages should be 0."""
        constituents = [
            IndexConstituent(
                symbol="A", company_name="A", isin="", industry="",
                last_price=100.0, change=0.0, change_pct=0.0,
                ffmc=0.0, is_fno=False, series="EQ",
            ),
        ]
        data = IndexData(
            index_name="TEST", last_price=0, change=0, change_pct=0,
            constituents=constituents,
        )
        weights = data.get_weightages()
        assert weights["A"] == 0.0


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — Parsing
# ═══════════════════════════════════════════════════════════════


class TestNSEParsing:
    def test_parse_constituents_basic(self):
        """Should parse index aggregate and stock constituents."""
        service = NSEIndexService()
        response_data = _make_nse_response("NIFTY 50")
        result = service._parse_constituents(response_data)

        assert result.index_name == "NIFTY 50"
        assert result.last_price == 22500.0
        assert result.change == 150.0
        assert result.change_pct == 0.67
        assert result.constituent_count == 3
        assert result.symbols == ["RELIANCE", "TCS", "INFY"]

    def test_parse_constituent_fields(self):
        service = NSEIndexService()
        result = service._parse_constituents(_make_nse_response())
        rel = result.constituents[0]

        assert rel.symbol == "RELIANCE"
        assert rel.company_name == "Reliance Industries"
        assert rel.isin == "INE002A01018"
        assert rel.industry == "Oil & Gas"
        assert rel.last_price == 2500.0
        assert rel.change == 25.0
        assert rel.change_pct == 1.01
        assert rel.ffmc == 1700000.0
        assert rel.is_fno is True
        assert rel.series == "EQ"

    def test_parse_empty_data_raises(self):
        service = NSEIndexService()
        with pytest.raises(NSEIndexError, match="Empty response"):
            service._parse_constituents({"data": [], "metadata": {}})

    def test_parse_missing_meta(self):
        """Should handle stocks without meta gracefully."""
        service = NSEIndexService()
        response = {
            "data": [
                {"symbol": "TEST", "lastPrice": 100, "priority": 1},
                {"symbol": "STOCK1", "lastPrice": 50, "priority": 0},
            ],
            "metadata": {"indexName": "TEST"},
        }
        result = service._parse_constituents(response)
        assert result.constituent_count == 1
        assert result.constituents[0].symbol == "STOCK1"
        assert result.constituents[0].company_name == "STOCK1"  # falls back to symbol


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — Caching
# ═══════════════════════════════════════════════════════════════


class TestNSECaching:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        """Second call should return cached data without API call."""
        service = NSEIndexService(cache_ttl_seconds=60)

        # Pre-populate cache
        data = IndexData(
            index_name="NIFTY 50", last_price=22000, change=0, change_pct=0,
            constituents=[
                IndexConstituent(
                    symbol="RELIANCE", company_name="Reliance", isin="", industry="",
                    last_price=2500, change=0, change_pct=0, ffmc=100, is_fno=True, series="EQ",
                ),
            ],
            fetched_at=time.time(),  # fresh
        )
        service._cache["NIFTY 50"] = data

        result = await service.get_constituents("NIFTY 50")
        assert result.symbols == ["RELIANCE"]
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    async def test_cache_expired(self, _mock_redis_set, _mock_redis_get):
        """Expired cache entry should trigger a fresh fetch."""
        service = NSEIndexService(cache_ttl_seconds=1)

        # Pre-populate with expired cache
        data = IndexData(
            index_name="NIFTY 50", last_price=22000, change=0, change_pct=0,
            constituents=[],
            fetched_at=time.time() - 10,  # expired
        )
        service._cache["NIFTY 50"] = data

        # Mock the HTTP call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_nse_response("NIFTY 50")
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        result = await service.get_constituents("NIFTY 50")
        assert result.constituent_count == 3  # Fresh data
        await service.close()

    def test_clear_cache(self):
        service = NSEIndexService()
        service._cache["NIFTY 50"] = IndexData(
            index_name="NIFTY 50", last_price=0, change=0, change_pct=0,
            constituents=[],
        )
        service.clear_cache()
        assert len(service._cache) == 0

    def test_cache_status(self):
        service = NSEIndexService(cache_ttl_seconds=300)
        service._cache["NIFTY 50"] = IndexData(
            index_name="NIFTY 50", last_price=0, change=0, change_pct=0,
            constituents=[
                IndexConstituent(
                    symbol="A", company_name="A", isin="", industry="",
                    last_price=100, change=0, change_pct=0, ffmc=0, is_fno=False, series="EQ",
                ),
            ],
            fetched_at=time.time(),
        )
        status = service.get_cache_status()
        assert "NIFTY 50" in status["cached_indices"]
        assert status["cache_ttl_seconds"] == 300
        assert status["entries"]["NIFTY 50"]["constituents"] == 1
        assert status["entries"]["NIFTY 50"]["expired"] is False


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — Validation
# ═══════════════════════════════════════════════════════════════


class TestNSEValidation:
    @pytest.mark.asyncio
    async def test_unknown_index_raises(self):
        service = NSEIndexService()
        with pytest.raises(NSEIndexError, match="Unknown index"):
            await service.get_constituents("NONEXISTENT")
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    async def test_force_refresh_bypasses_cache(self, _mock_redis_set):
        """force_refresh=True should skip cache even if fresh."""
        service = NSEIndexService(cache_ttl_seconds=3600)

        # Pre-populate cache with fresh data
        service._cache["NIFTY IT"] = IndexData(
            index_name="NIFTY IT", last_price=0, change=0, change_pct=0,
            constituents=[],
            fetched_at=time.time(),
        )

        # Mock HTTP call
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_nse_response("NIFTY IT")
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        result = await service.get_constituents("NIFTY IT", force_refresh=True)
        assert result.constituent_count == 3  # Got new data, not cached empty
        await service.close()


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — Error Handling
# ═══════════════════════════════════════════════════════════════


class TestNSEErrorHandling:
    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    async def test_http_error_raises_nse_error(self, _mock_redis_get):
        """HTTP errors should be wrapped in NSEIndexError."""
        service = NSEIndexService()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response,
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        with pytest.raises(NSEIndexError, match="500"):
            await service.get_constituents("NIFTY 50")
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    async def test_session_reestablish_on_401(self, _mock_redis_set, _mock_redis_get):
        """On 401, service should re-establish session and retry."""
        service = NSEIndexService()

        # First call returns 401, then session re-established, second call succeeds
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = _make_nse_response()
        success_response.raise_for_status = MagicMock()

        fail_response = MagicMock()
        fail_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                # establish_session homepage call
                MagicMock(raise_for_status=MagicMock()),
                # first API call → 401
                fail_response,
                # re-establish session
                MagicMock(raise_for_status=MagicMock()),
                # retry API call → success
                success_response,
            ]
        )
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = False

        result = await service.get_constituents("NIFTY 50")
        assert result.constituent_count == 3
        await service.close()


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — Convenience Methods
# ═══════════════════════════════════════════════════════════════


class TestConvenienceMethods:
    @pytest.mark.asyncio
    async def test_get_constituent_symbols(self):
        service = NSEIndexService()
        service._cache["NIFTY IT"] = IndexData(
            index_name="NIFTY IT", last_price=0, change=0, change_pct=0,
            constituents=[
                IndexConstituent(
                    symbol="TCS", company_name="TCS", isin="", industry="",
                    last_price=0, change=0, change_pct=0, ffmc=0, is_fno=True, series="EQ",
                ),
                IndexConstituent(
                    symbol="INFY", company_name="Infosys", isin="", industry="",
                    last_price=0, change=0, change_pct=0, ffmc=0, is_fno=True, series="EQ",
                ),
            ],
            fetched_at=time.time(),
        )
        symbols = await service.get_constituent_symbols("NIFTY IT")
        assert symbols == ["TCS", "INFY"]
        await service.close()

    @pytest.mark.asyncio
    async def test_get_all_constituent_symbols(self):
        service = NSEIndexService()
        # Pre-populate cache
        for name in ["NIFTY IT", "NIFTY BANK"]:
            service._cache[name] = IndexData(
                index_name=name, last_price=0, change=0, change_pct=0,
                constituents=[
                    IndexConstituent(
                        symbol=f"{name}_STOCK", company_name="", isin="", industry="",
                        last_price=0, change=0, change_pct=0, ffmc=0, is_fno=False, series="EQ",
                    ),
                ],
                fetched_at=time.time(),
            )
        result = await service.get_all_constituent_symbols(indices=["NIFTY IT", "NIFTY BANK"])
        assert "NIFTY IT" in result
        assert "NIFTY BANK" in result
        assert result["NIFTY IT"] == ["NIFTY IT_STOCK"]
        await service.close()


# ═══════════════════════════════════════════════════════════════
#  NSEIndexError
# ═══════════════════════════════════════════════════════════════


class TestNSEIndexError:
    def test_error_attributes(self):
        err = NSEIndexError("test error", index_name="NIFTY 50", status_code=403)
        assert str(err) == "test error"
        assert err.index_name == "NIFTY 50"
        assert err.status_code == 403

    def test_error_defaults(self):
        err = NSEIndexError("fail")
        assert err.index_name == ""
        assert err.status_code == 0
