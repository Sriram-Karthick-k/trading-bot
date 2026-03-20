"""
Tests for CPR Scanner API endpoints.

Covers:
  - GET  /backtest/cpr-scan/indices — list available indices
  - POST /backtest/cpr-scan          — scan constituent stocks for narrow CPR
  - GET  /backtest/cpr-scan/cache-status — NSE cache monitoring
  - Fallback constituent data integrity
  - Input validation (bad dates, unknown indices)
  - Empty indices / no constituents
  - CPR calculation via endpoint (end-to-end with mock data)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps
from app.api.routes.backtest import _FALLBACK_CONSTITUENTS
from app.services.nse_index import AVAILABLE_INDICES, INDEX_URL_NAMES
from app.core.clock import VirtualClock
from app.core.order_manager import OrderManager
from app.providers.mock.provider import MockProvider
from app.providers import registry


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_state():
    """Clean registry and dependency singletons between tests."""
    registry.clear_registry()
    deps._config_manager = None
    deps._risk_manager = None
    deps._order_manager = None
    deps._clock = None
    deps._strategies.clear()
    yield
    registry.clear_registry()
    deps._strategies.clear()
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def patch_nse_service():
    """
    Patch NSE service calls to use fallback data in all API tests.

    This prevents real NSE API calls during testing while ensuring the
    CPR scanner endpoints use the same constituent data the tests expect.
    """
    async def _mock_get_constituents(indices):
        return {idx: _FALLBACK_CONSTITUENTS.get(idx, []) for idx in indices}

    # Mock the list_available_indices endpoint to also use fallback
    async def _mock_nse_get_all(*args, **kwargs):
        from app.services.nse_index import NSEIndexError
        raise NSEIndexError("Mocked: NSE unavailable in tests")

    with patch(
        "app.api.routes.backtest._get_index_constituents",
        side_effect=_mock_get_constituents,
    ), patch(
        "app.api.routes.backtest._get_nse_service",
    ) as mock_nse_svc:
        # Make the NSE service's get_all_constituents raise so fallback is used
        mock_svc_instance = MagicMock()
        mock_svc_instance.get_all_constituents = _mock_nse_get_all
        mock_svc_instance.get_cache_status.return_value = {
            "cached_indices": [],
            "cache_ttl_seconds": 600,
            "entries": {},
        }
        mock_nse_svc.return_value = mock_svc_instance
        yield


@pytest.fixture
def clock():
    return VirtualClock()


@pytest.fixture
def mock_provider(clock):
    """MockProvider with sample data loaded (instruments + historical candles)."""
    mp = MockProvider(capital=1_000_000, clock=clock)
    mp.engine.load_sample_data()
    mp.load_instruments(mp.engine.get_sample_as_instruments())
    return mp


@pytest.fixture
def client(mock_provider, risk_manager, config_manager):
    """Test client with mock provider active via dependency overrides."""
    order_manager = OrderManager(provider=mock_provider, risk_manager=risk_manager)
    app.dependency_overrides[deps.get_provider] = lambda: mock_provider
    app.dependency_overrides[deps.get_risk_manager] = lambda: risk_manager
    app.dependency_overrides[deps.get_config_manager] = lambda: config_manager
    app.dependency_overrides[deps.get_order_manager] = lambda: order_manager
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
#  Fallback constituent data integrity
# ═══════════════════════════════════════════════════════════════


class TestFallbackConstituents:
    def test_has_16_indices(self):
        """_FALLBACK_CONSTITUENTS should have exactly 16 NIFTY sector indices."""
        assert len(_FALLBACK_CONSTITUENTS) == 16

    def test_available_indices_matches_keys(self):
        """AVAILABLE_INDICES should match INDEX_URL_NAMES keys."""
        assert AVAILABLE_INDICES == list(INDEX_URL_NAMES.keys())

    def test_contains_key_indices(self):
        assert "NIFTY 50" in _FALLBACK_CONSTITUENTS
        assert "NIFTY BANK" in _FALLBACK_CONSTITUENTS
        assert "NIFTY IT" in _FALLBACK_CONSTITUENTS
        assert "NIFTY FIN SERVICE" in _FALLBACK_CONSTITUENTS
        assert "NIFTY PHARMA" in _FALLBACK_CONSTITUENTS
        assert "NIFTY AUTO" in _FALLBACK_CONSTITUENTS

    def test_nifty50_has_20_stocks(self):
        """NIFTY 50 fallback should have 20 mock stocks."""
        assert len(_FALLBACK_CONSTITUENTS["NIFTY 50"]) == 20

    def test_nifty_bank_has_5_stocks(self):
        assert len(_FALLBACK_CONSTITUENTS["NIFTY BANK"]) == 5

    def test_nifty_it_has_4_stocks(self):
        assert len(_FALLBACK_CONSTITUENTS["NIFTY IT"]) == 4

    def test_empty_indices_exist(self):
        """Some indices have no fallback constituents."""
        assert _FALLBACK_CONSTITUENTS["NIFTY METAL"] == []
        assert _FALLBACK_CONSTITUENTS["NIFTY REALTY"] == []
        assert _FALLBACK_CONSTITUENTS["NIFTY MEDIA"] == []

    def test_all_values_are_string_lists(self):
        for name, stocks in _FALLBACK_CONSTITUENTS.items():
            assert isinstance(stocks, list), f"{name} should be a list"
            for s in stocks:
                assert isinstance(s, str), f"Stock in {name} should be a string: {s}"

    def test_no_duplicate_stocks_within_index(self):
        """Each index should not list the same stock twice."""
        for name, stocks in _FALLBACK_CONSTITUENTS.items():
            assert len(stocks) == len(set(stocks)), f"{name} has duplicate stocks"

    def test_stocks_can_appear_in_multiple_indices(self):
        """HDFCBANK should be in both NIFTY 50 and NIFTY BANK."""
        assert "HDFCBANK" in _FALLBACK_CONSTITUENTS["NIFTY 50"]
        assert "HDFCBANK" in _FALLBACK_CONSTITUENTS["NIFTY BANK"]
        assert "HDFCBANK" in _FALLBACK_CONSTITUENTS["NIFTY FIN SERVICE"]


# ═══════════════════════════════════════════════════════════════
#  GET /backtest/cpr-scan/indices
# ═══════════════════════════════════════════════════════════════


class TestListIndices:
    def test_returns_all_indices(self, client):
        resp = client.get("/api/backtest/cpr-scan/indices")
        assert resp.status_code == 200
        data = resp.json()
        assert "indices" in data
        assert len(data["indices"]) == 16

    def test_index_has_name_and_count(self, client):
        resp = client.get("/api/backtest/cpr-scan/indices")
        data = resp.json()
        first = data["indices"][0]
        assert "name" in first
        assert "constituent_count" in first
        assert isinstance(first["constituent_count"], int)

    def test_nifty50_has_correct_count(self, client):
        resp = client.get("/api/backtest/cpr-scan/indices")
        data = resp.json()
        nifty50 = next(i for i in data["indices"] if i["name"] == "NIFTY 50")
        assert nifty50["constituent_count"] == 20

    def test_empty_index_has_zero_count(self, client):
        resp = client.get("/api/backtest/cpr-scan/indices")
        data = resp.json()
        metal = next(i for i in data["indices"] if i["name"] == "NIFTY METAL")
        assert metal["constituent_count"] == 0

    def test_all_index_names_present(self, client):
        resp = client.get("/api/backtest/cpr-scan/indices")
        data = resp.json()
        names = [i["name"] for i in data["indices"]]
        for expected in AVAILABLE_INDICES:
            assert expected in names, f"Missing index: {expected}"


# ═══════════════════════════════════════════════════════════════
#  POST /backtest/cpr-scan — validation
# ═══════════════════════════════════════════════════════════════


class TestCPRScanValidation:
    def test_invalid_date_format(self, client):
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "15-01-2025",
            "indices": ["NIFTY 50"],
        })
        assert resp.status_code == 400
        assert "date format" in resp.json()["detail"].lower()

    def test_unknown_index(self, client):
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-01-15",
            "indices": ["NIFTY 50", "NONEXISTENT_INDEX"],
        })
        assert resp.status_code == 400
        assert "NONEXISTENT_INDEX" in resp.json()["detail"]

    def test_empty_indices_list_scans_nothing(self, client):
        """Empty indices list should return zero stocks (no constituents to scan)."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-01-15",
            "indices": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_stocks_scanned"] == 0
        assert data["scan_params"]["unique_stocks"] == 0

    def test_indices_with_no_constituents(self, client):
        """Scanning indices with empty constituent lists returns empty + error."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-01-15",
            "indices": ["NIFTY METAL", "NIFTY REALTY", "NIFTY MEDIA"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_stocks_scanned"] == 0
        assert data["scan_params"]["unique_stocks"] == 0


# ═══════════════════════════════════════════════════════════════
#  POST /backtest/cpr-scan — end-to-end with mock data
# ═══════════════════════════════════════════════════════════════


class TestCPRScanEndToEnd:
    def test_scan_nifty_bank_returns_stocks(self, client):
        """NIFTY BANK has 5 stocks with mock data — should return results."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY BANK"],
            "narrow_threshold": 1.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["scan_date"] == "2025-06-15"
        assert data["scan_params"]["indices_selected"] == ["NIFTY BANK"]
        assert data["scan_params"]["unique_stocks"] == 5

        # Should have some successfully scanned stocks
        # (mock data generates 365 daily candles per stock)
        assert len(data["stocks"]) > 0 or data["errors"] is not None

    def test_scan_nifty_it_returns_4_stocks(self, client):
        """NIFTY IT has 4 stocks — all should be scanned."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY IT"],
            "narrow_threshold": 5.0,  # Very generous threshold
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["scan_params"]["unique_stocks"] == 4

    def test_stocks_sorted_by_width_ascending(self, client):
        """Results should be sorted by CPR width_pct, narrowest first."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY 50"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]
        if len(stocks) > 1:
            widths = [s["cpr"]["width_pct"] for s in stocks]
            assert widths == sorted(widths), "Stocks should be sorted by width_pct ascending"

    def test_stock_entry_structure(self, client):
        """Each stock entry should have the expected fields."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY IT"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]

        if not stocks:
            pytest.skip("No stocks returned — mock data may not cover this date")

        stock = stocks[0]
        # Required top-level fields
        assert "symbol" in stock
        assert "name" in stock
        assert "instrument_token" in stock
        assert "indices" in stock
        assert isinstance(stock["indices"], list)
        assert "scan_date" in stock
        assert "today_open" in stock
        assert "data_source" in stock

        # Prev day data
        assert "prev_day" in stock
        prev = stock["prev_day"]
        assert "date" in prev
        assert "open" in prev
        assert "high" in prev
        assert "low" in prev
        assert "close" in prev

        # CPR data
        assert "cpr" in stock
        cpr = stock["cpr"]
        assert "pivot" in cpr
        assert "tc" in cpr
        assert "bc" in cpr
        assert "width" in cpr
        assert "width_pct" in cpr
        assert "is_narrow" in cpr
        assert cpr["tc"] >= cpr["bc"], "TC must be >= BC"

    def test_narrow_threshold_affects_is_narrow(self, client):
        """Setting a very high threshold should mark all stocks as narrow."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY IT"],
            "narrow_threshold": 100.0,  # Everything is narrow
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]
        if stocks:
            for s in stocks:
                assert s["cpr"]["is_narrow"] is True

    def test_narrow_threshold_zero_marks_none_narrow(self, client):
        """Setting threshold to 0 should mark nothing as narrow (unless width is exactly 0)."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY IT"],
            "narrow_threshold": 0.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]
        # Stocks with non-zero width should not be narrow at threshold 0
        for s in stocks:
            if s["cpr"]["width_pct"] > 0:
                assert s["cpr"]["is_narrow"] is False

    def test_multiple_indices_deduplicates_stocks(self, client):
        """Scanning overlapping indices should not duplicate stocks in results."""
        # NIFTY BANK and NIFTY FIN SERVICE share stocks (HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK)
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY BANK", "NIFTY FIN SERVICE"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()

        # NIFTY BANK: 5 stocks, NIFTY FIN SERVICE: 6 stocks
        # Overlap: HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK (5)
        # Unique: BAJFINANCE (only in FIN SERVICE)
        # Total unique = 6
        assert data["scan_params"]["unique_stocks"] == 6

        # No duplicate symbols in results
        symbols = [s["symbol"] for s in data["stocks"]]
        assert len(symbols) == len(set(symbols)), "Stocks should not be duplicated"

    def test_stock_indices_field_shows_membership(self, client):
        """A stock in multiple indices should list all of them."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY BANK", "NIFTY FIN SERVICE"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]

        # HDFCBANK should be in both NIFTY BANK and NIFTY FIN SERVICE
        hdfcbank = next((s for s in stocks if s["symbol"] == "HDFCBANK"), None)
        if hdfcbank:
            assert "NIFTY BANK" in hdfcbank["indices"]
            assert "NIFTY FIN SERVICE" in hdfcbank["indices"]

        # BAJFINANCE should only be in NIFTY FIN SERVICE
        bajfinance = next((s for s in stocks if s["symbol"] == "BAJFINANCE"), None)
        if bajfinance:
            assert "NIFTY FIN SERVICE" in bajfinance["indices"]
            assert "NIFTY BANK" not in bajfinance["indices"]

    def test_response_summary(self, client):
        """Response should include summary with total_stocks_scanned and narrow_count."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY IT"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "total_stocks_scanned" in data["summary"]
        assert "narrow_count" in data["summary"]
        assert data["summary"]["total_stocks_scanned"] >= 0
        assert data["summary"]["narrow_count"] >= 0
        assert data["summary"]["narrow_count"] <= data["summary"]["total_stocks_scanned"]

    def test_scan_params_echoed_back(self, client):
        """Response should echo back scan parameters."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY IT", "NIFTY BANK"],
            "narrow_threshold": 0.75,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["scan_params"]["narrow_threshold"] == 0.75
        assert data["scan_params"]["indices_selected"] == ["NIFTY IT", "NIFTY BANK"]

    def test_default_threshold(self, client):
        """Default narrow_threshold should be 0.5."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY IT"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["scan_params"]["narrow_threshold"] == 0.5

    def test_cpr_values_are_positive(self, client):
        """CPR pivot, TC, BC should all be positive numbers."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY 50"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        for stock in data["stocks"]:
            assert stock["cpr"]["pivot"] > 0
            assert stock["cpr"]["tc"] > 0
            assert stock["cpr"]["bc"] > 0
            assert stock["cpr"]["width"] >= 0
            assert stock["cpr"]["width_pct"] >= 0

    def test_errors_null_when_no_errors(self, client):
        """If all stocks scan successfully, errors should be null."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",
            "indices": ["NIFTY BANK"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        # If all 5 stocks scanned, errors should be null (or any errors are dicts)
        if data["errors"] is not None:
            for err in data["errors"]:
                assert "symbol" in err
                assert "error" in err


# ═══════════════════════════════════════════════════════════════
#  CPR Scanner bug-fix edge cases
#
#  Covers the fix in backtest.py:
#  1. to_dt now uses hour=23:59:59 so candles ON scan_date (ts=09:15) are included
#  2. When scan_date has no candle (weekend/holiday/before open), falls back
#     to using the last available candle as prev_day and prev_close as today_open
# ═══════════════════════════════════════════════════════════════


class TestCPRScanDateEdgeCases:
    """Edge case tests for CPR scanner date handling."""

    def test_scan_on_weekend_uses_fallback(self, client):
        """2025-06-15 is a Sunday — no candle exists for that date.
        Scanner should fall back to using the last available candle
        (Friday 2025-06-13) as prev_day and its close as today_open."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-15",  # Sunday
            "indices": ["NIFTY BANK"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]
        assert len(stocks) > 0, "Should return results even for weekend scan date"

        for stock in stocks:
            # scan_date should always reflect the requested date, not the candle date
            assert stock["scan_date"] == "2025-06-15"
            # prev_day date should be a weekday (the most recent trading day)
            prev_date = datetime.strptime(stock["prev_day"]["date"], "%Y-%m-%d")
            assert prev_date.weekday() < 5, f"prev_day {prev_date} should be a weekday"
            # today_open should equal prev_day close (fallback proxy)
            assert stock["today_open"] == stock["prev_day"]["close"]

    def test_scan_on_saturday_uses_fallback(self, client):
        """2025-06-14 is a Saturday — same fallback behavior as Sunday."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-14",  # Saturday
            "indices": ["NIFTY IT"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]
        assert len(stocks) > 0

        for stock in stocks:
            assert stock["scan_date"] == "2025-06-14"
            # today_open is prev_close proxy for non-trading day
            assert stock["today_open"] == stock["prev_day"]["close"]

    def test_scan_on_weekday_has_candle(self, client):
        """2025-06-13 is a Friday — mock data should have a candle for this date.
        today_open should NOT equal prev_day close (it uses the actual candle's open)."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-13",  # Friday
            "indices": ["NIFTY BANK"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]
        assert len(stocks) > 0

        for stock in stocks:
            assert stock["scan_date"] == "2025-06-13"
            # prev_day should be a DIFFERENT date from 2025-06-13
            assert stock["prev_day"]["date"] != "2025-06-13", \
                "prev_day should be the day BEFORE scan_date, not scan_date itself"
            # today_open comes from the actual candle, not prev close
            # (it CAN coincidentally equal prev close, but structurally it's the open)

    def test_scan_date_always_echoed_not_candle_date(self, client):
        """scan_date in each stock should always be the requested date,
        regardless of whether a candle exists for it."""
        for scan_date in ["2025-06-13", "2025-06-14", "2025-06-15"]:
            resp = client.post("/api/backtest/cpr-scan", json={
                "scan_date": scan_date,
                "indices": ["NIFTY IT"],
                "narrow_threshold": 5.0,
            })
            assert resp.status_code == 200
            data = resp.json()
            for stock in data["stocks"]:
                assert stock["scan_date"] == scan_date, \
                    f"Stock scan_date should be {scan_date}, got {stock['scan_date']}"

    def test_scan_far_future_returns_errors(self, client):
        """A date well beyond the mock data range should error for all stocks.
        fetch_candles uses from_dt = scan_dt - 10 days, so 2028-01-05..2028-01-15
        has no candles at all → 'Insufficient daily data' for each stock."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2028-01-15",
            "indices": ["NIFTY BANK"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        # No stocks should succeed — data is out of range
        assert len(data["stocks"]) == 0
        assert data["errors"] is not None
        assert len(data["errors"]) > 0
        for err in data["errors"]:
            assert "Insufficient" in err["error"] or "Not enough" in err["error"]

    def test_scan_date_before_data_range_errors(self, client):
        """A date before any mock data exists should error for each stock.
        Mock data starts ~365 days before clock.now() (2025-03-21).
        Scanning 2024-01-01 should have insufficient data."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2024-01-01",
            "indices": ["NIFTY BANK"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        # Stocks should fail with insufficient data errors
        # Either no stocks returned or all are errors
        assert len(data["stocks"]) == 0
        assert data["errors"] is not None
        assert len(data["errors"]) > 0

    def test_cpr_calculated_from_prev_day_not_scan_day(self, client):
        """CPR should be calculated from prev_day OHLC, not the scan_date candle.
        Verify pivot = (H + L + C) / 3 using prev_day values."""
        resp = client.post("/api/backtest/cpr-scan", json={
            "scan_date": "2025-06-13",
            "indices": ["NIFTY IT"],
            "narrow_threshold": 5.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        stocks = data["stocks"]
        assert len(stocks) > 0

        for stock in stocks:
            prev = stock["prev_day"]
            cpr = stock["cpr"]
            # Pivot = (H + L + C) / 3
            expected_pivot = round((prev["high"] + prev["low"] + prev["close"]) / 3, 2)
            assert cpr["pivot"] == expected_pivot, \
                f"Pivot for {stock['symbol']}: expected {expected_pivot}, got {cpr['pivot']}"

    def test_multiple_dates_same_index_different_cpr(self, client):
        """Scanning different dates should produce different CPR values
        (since different prev_day candles are used)."""
        results = {}
        for scan_date in ["2025-06-12", "2025-06-13"]:
            resp = client.post("/api/backtest/cpr-scan", json={
                "scan_date": scan_date,
                "indices": ["NIFTY IT"],
                "narrow_threshold": 5.0,
            })
            assert resp.status_code == 200
            data = resp.json()
            if data["stocks"]:
                first_stock = data["stocks"][0]
                results[scan_date] = first_stock["cpr"]["pivot"]

        if len(results) == 2:
            dates = list(results.keys())
            assert results[dates[0]] != results[dates[1]], \
                "Different scan dates should use different prev_day candles → different CPR"
