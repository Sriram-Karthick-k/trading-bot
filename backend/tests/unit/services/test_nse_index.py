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
        """Non-retryable HTTP errors should be wrapped in NSEIndexError."""
        service = NSEIndexService()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response,
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        with pytest.raises(NSEIndexError, match="404"):
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


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — Retry Logic (_fetch_with_retry)
# ═══════════════════════════════════════════════════════════════


class TestFetchWithRetry:
    """Tests for the _fetch_with_retry method with exponential backoff."""

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    async def test_success_on_first_try(self, _rs, _rg):
        """Should return data on first successful attempt."""
        service = NSEIndexService(rate_limit_delay=0)

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

        result = await service.get_constituents("NIFTY IT")
        assert result.constituent_count == 3
        # Should only call get once (the actual API call)
        assert mock_client.get.call_count == 1
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_on_429_then_success(self, mock_sleep, _rs, _rg):
        """429 should trigger retry with backoff, then succeed."""
        service = NSEIndexService(rate_limit_delay=0)

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = _make_nse_response("NIFTY IT")
        success.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[rate_limited, success])
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        result = await service.get_constituents("NIFTY IT")
        assert result.constituent_count == 3
        # asyncio.sleep should have been called for the backoff
        assert mock_sleep.call_count >= 1
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_on_429_with_retry_after_header(self, mock_sleep, _rg):
        """429 with Retry-After header should wait the specified time."""
        service = NSEIndexService(rate_limit_delay=0)

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "5"}

        # All 3 retries return 429 → should raise
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=rate_limited)
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        with pytest.raises(NSEIndexError, match="failed after"):
            await service.get_constituents("NIFTY IT")

        # Check that sleep was called with 5.0 (from Retry-After header)
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        assert any(abs(arg - 5.0) < 0.1 for arg in sleep_args), \
            f"Expected sleep(5.0) from Retry-After, got: {sleep_args}"
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_on_500_with_exponential_backoff(self, mock_sleep, _rg):
        """500 errors should use exponential backoff: 2, 4, 8 seconds."""
        service = NSEIndexService(rate_limit_delay=0)

        server_error = MagicMock()
        server_error.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=server_error)
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        with pytest.raises(NSEIndexError, match="failed after 3 retries"):
            await service.get_constituents("NIFTY IT")

        # Check backoff: should sleep at 2.0, 4.0 (attempts 0, 1 before last attempt fails)
        sleep_args = [call.args[0] for call in mock_sleep.call_args_list]
        backoff_sleeps = [a for a in sleep_args if a >= 2.0]
        assert len(backoff_sleeps) >= 2, f"Expected at least 2 backoff sleeps, got: {sleep_args}"
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_on_timeout_then_success(self, mock_sleep, _rs, _rg):
        """Timeout errors should be retried."""
        service = NSEIndexService(rate_limit_delay=0)

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = _make_nse_response("NIFTY IT")
        success.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            httpx.ReadTimeout("Timed out"),
            success,
        ])
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        result = await service.get_constituents("NIFTY IT")
        assert result.constituent_count == 3
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_all_retries_exhausted(self, mock_sleep, _rg):
        """After MAX_RETRIES failures, should raise NSEIndexError."""
        service = NSEIndexService(rate_limit_delay=0)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        with pytest.raises(NSEIndexError, match="failed after 3 retries"):
            await service.get_constituents("NIFTY IT")
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_consecutive_failures_increment(self, mock_sleep, _rs, _rg):
        """_consecutive_failures should increment on retryable errors and decrement on success."""
        service = NSEIndexService(rate_limit_delay=0)
        assert service._consecutive_failures == 0

        # Fail twice (502), then succeed
        fail_502 = MagicMock()
        fail_502.status_code = 502

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = _make_nse_response("NIFTY IT")
        success.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[fail_502, fail_502, success])
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        result = await service.get_constituents("NIFTY IT")
        assert result.constituent_count == 3
        # After 2 failures and 1 success: failures went 0→1→2→1 (decremented on success)
        assert service._consecutive_failures == 1
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_get", new_callable=AsyncMock, return_value=None)
    @patch("app.services.nse_index.redis_set", new_callable=AsyncMock, return_value=True)
    async def test_401_reestablishes_session(self, _rs, _rg):
        """401 response should trigger session re-establishment."""
        service = NSEIndexService(rate_limit_delay=0)

        fail_401 = MagicMock()
        fail_401.status_code = 401

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = _make_nse_response("NIFTY IT")
        success.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            fail_401,  # First API call → 401
            MagicMock(raise_for_status=MagicMock()),  # Re-establish session
            success,  # Retry API call → success
        ])
        mock_client.is_closed = False
        mock_client.cookies = MagicMock()
        mock_client.cookies.keys.return_value = []

        service._client = mock_client
        service._session_established = True
        service._session_time = time.time()

        result = await service.get_constituents("NIFTY IT")
        assert result.constituent_count == 3
        # get() should be called 3 times: initial fail, session re-establish, retry
        assert mock_client.get.call_count == 3
        await service.close()


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — Batch Abort (get_all_constituents)
# ═══════════════════════════════════════════════════════════════


class TestBatchAbort:
    """Tests for early batch abort when consecutive indices fail."""

    @pytest.mark.asyncio
    async def test_batch_stops_after_3_consecutive_failures(self):
        """get_all_constituents should stop after 3 consecutive failures."""
        service = NSEIndexService(rate_limit_delay=0)

        call_count = 0

        async def _mock_get_constituents(index_name, force_refresh=False):
            nonlocal call_count
            call_count += 1
            raise NSEIndexError(f"Mock failure for {index_name}")

        service.get_constituents = _mock_get_constituents  # type: ignore

        results = await service.get_all_constituents(
            indices=["NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA"]
        )
        assert len(results) == 0
        # Should stop after 3 consecutive failures, not try all 5
        assert call_count == 3
        await service.close()

    @pytest.mark.asyncio
    async def test_batch_resets_counter_on_success(self):
        """Success should reset the consecutive failure counter."""
        service = NSEIndexService(rate_limit_delay=0)

        call_sequence = []

        async def _mock_get_constituents(index_name, force_refresh=False):
            call_sequence.append(index_name)
            if index_name in ("NIFTY BANK", "NIFTY IT"):
                raise NSEIndexError(f"Mock failure for {index_name}")
            return IndexData(
                index_name=index_name, last_price=0, change=0, change_pct=0,
                constituents=[], fetched_at=time.time(),
            )

        service.get_constituents = _mock_get_constituents  # type: ignore

        results = await service.get_all_constituents(
            indices=["NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY PHARMA"]
        )
        # NIFTY 50 succeeds, BANK fails, IT fails (2 consecutive), AUTO succeeds (resets), PHARMA succeeds
        assert len(call_sequence) == 5  # All 5 should be attempted
        assert "NIFTY 50" in results
        assert "NIFTY AUTO" in results
        assert "NIFTY PHARMA" in results
        assert "NIFTY BANK" not in results
        await service.close()


# ═══════════════════════════════════════════════════════════════
#  NSEIndexService — clear_all_cache
# ═══════════════════════════════════════════════════════════════


class TestClearAllCache:
    """Tests for the clear_all_cache method (memory + Redis)."""

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_delete", new_callable=AsyncMock, return_value=True)
    async def test_clears_memory_and_redis(self, mock_redis_del):
        """clear_all_cache should clear in-memory cache and delete all Redis keys."""
        service = NSEIndexService()
        # Pre-populate memory cache
        service._cache["NIFTY 50"] = IndexData(
            index_name="NIFTY 50", last_price=0, change=0, change_pct=0,
            constituents=[], fetched_at=time.time(),
        )
        service._cache["NIFTY IT"] = IndexData(
            index_name="NIFTY IT", last_price=0, change=0, change_pct=0,
            constituents=[], fetched_at=time.time(),
        )
        service._consecutive_failures = 5

        deleted = await service.clear_all_cache()

        # Memory cache should be empty
        assert len(service._cache) == 0
        # Consecutive failures should be reset
        assert service._consecutive_failures == 0
        # redis_delete should be called for all 16 indices
        assert mock_redis_del.call_count == 16
        # All returned True so deleted count = 16
        assert deleted == 16
        await service.close()

    @pytest.mark.asyncio
    @patch("app.services.nse_index.redis_delete", new_callable=AsyncMock, return_value=False)
    async def test_redis_delete_failures_counted(self, mock_redis_del):
        """If redis_delete returns False, it shouldn't be counted as deleted."""
        service = NSEIndexService()
        deleted = await service.clear_all_cache()
        assert deleted == 0
        await service.close()


# ═══════════════════════════════════════════════════════════════
#  Redis auto-retry
# ═══════════════════════════════════════════════════════════════


class TestRedisAutoRetry:
    """Tests for the Redis auto-retry mechanism in redis_client."""

    @pytest.mark.asyncio
    async def test_redis_retries_after_interval(self):
        """After _REDIS_RETRY_INTERVAL elapses, get_redis should retry."""
        from app.services import redis_client

        # Save original state
        orig_client = redis_client._redis_client
        orig_unavailable = redis_client._redis_unavailable
        orig_since = redis_client._redis_unavailable_since

        try:
            # Simulate Redis being unavailable for more than the retry interval
            redis_client._redis_unavailable = True
            redis_client._redis_unavailable_since = time.time() - redis_client._REDIS_RETRY_INTERVAL - 1
            redis_client._redis_client = None

            # Mock from_url so reconnection fails (real Redis may be running in test env)
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("mocked connection failure"))

            with patch("redis.asyncio.from_url", return_value=mock_redis):
                result = await redis_client.get_redis()

            # Reconnection was attempted but failed → returns None, marked unavailable again
            assert result is None
            assert redis_client._redis_unavailable is True
        finally:
            # Restore original state
            redis_client._redis_client = orig_client
            redis_client._redis_unavailable = orig_unavailable
            redis_client._redis_unavailable_since = orig_since

    @pytest.mark.asyncio
    async def test_redis_does_not_retry_before_interval(self):
        """Before _REDIS_RETRY_INTERVAL elapses, get_redis should return None immediately."""
        from app.services import redis_client

        orig_unavailable = redis_client._redis_unavailable
        orig_since = redis_client._redis_unavailable_since

        try:
            redis_client._redis_unavailable = True
            redis_client._redis_unavailable_since = time.time()  # Just now

            result = await redis_client.get_redis()
            assert result is None
            # Should still be marked unavailable (didn't attempt reconnect)
            assert redis_client._redis_unavailable is True
        finally:
            redis_client._redis_unavailable = orig_unavailable
            redis_client._redis_unavailable_since = orig_since
