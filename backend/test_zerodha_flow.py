#!/usr/bin/env python3
"""
Zerodha Integration Test Script
================================
Tests all API endpoints against the running server.

Usage:
    # Phase 1: Test pre-auth endpoints (no login needed)
    python test_zerodha_flow.py

    # Phase 2: After you login via the browser, pass the request_token:
    python test_zerodha_flow.py --request-token <TOKEN>

    # Phase 3: Once authenticated, test all market/order endpoints:
    python test_zerodha_flow.py --authenticated

The Kite Connect OAuth flow:
1. GET /api/auth/login-url → gives you the Zerodha login URL
2. Open that URL in browser → login with your Zerodha credentials
3. Zerodha redirects to: http://localhost:8000/api/auth/redirect?request_token=XXX
   - If redirect URL is configured correctly, the server auto-exchanges the token
   - If not, copy the request_token from the URL and run:
     python test_zerodha_flow.py --request-token <TOKEN>
4. Now all authenticated endpoints work
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

import requests

BASE = "http://localhost:8000/api"
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

results = {"passed": 0, "failed": 0, "skipped": 0}


def test(name: str, fn):
    """Run a single test and print result."""
    try:
        result = fn()
        if result is None or result is True:
            print(f"  {PASS} {name}")
            results["passed"] += 1
        elif result == "skip":
            print(f"  {WARN} {name} (skipped)")
            results["skipped"] += 1
        else:
            print(f"  {FAIL} {name}: {result}")
            results["failed"] += 1
    except Exception as e:
        print(f"  {FAIL} {name}: {e}")
        results["failed"] += 1


def get(path, **kwargs):
    return requests.get(f"{BASE}{path}", timeout=10, **kwargs)


def post(path, **kwargs):
    return requests.post(f"{BASE}{path}", timeout=10, **kwargs)


def put(path, **kwargs):
    return requests.put(f"{BASE}{path}", timeout=10, **kwargs)


# ─────────────────────────────────────────────────────────────
#  PHASE 1: Pre-auth tests (always work)
# ─────────────────────────────────────────────────────────────

def test_phase1():
    print(f"\n{BOLD}═══ PHASE 1: Server & Provider Status (no auth needed) ═══{RESET}\n")

    # Health
    def t_health():
        r = get("/health")
        assert r.status_code == 200, f"status={r.status_code}"
        d = r.json()
        assert d["status"] == "ok", f"status={d['status']}"
        assert d["version"] == "0.1.0"
    test("Health endpoint", t_health)

    # Provider list
    def t_providers_list():
        r = get("/providers/")
        assert r.status_code == 200, f"status={r.status_code}"
        providers = r.json()
        names = [p["name"] for p in providers]
        assert "zerodha" in names, f"zerodha not in {names}"
        assert "mock" in names, f"mock not in {names}"
        zerodha = next(p for p in providers if p["name"] == "zerodha")
        assert zerodha["is_active"], "zerodha should be active"
        assert zerodha["instantiated"], "zerodha should be instantiated"
    test("Provider list shows zerodha active", t_providers_list)

    # Active provider
    def t_active():
        r = get("/providers/active")
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "zerodha", f"active={d.get('name')}"
        assert "NSE" in d["supported_exchanges"]
    test("Active provider is zerodha", t_active)

    # Zerodha health (will be unhealthy until authenticated)
    def t_zerodha_health():
        r = get("/providers/zerodha/health")
        assert r.status_code == 200
        d = r.json()
        if d["healthy"]:
            print(f"    → Already authenticated! (latency: {d['latency_ms']:.1f}ms)")
            return True
        else:
            print(f"    → Not authenticated: {d['message']}")
            return True  # Expected at this phase
    test("Zerodha provider health", t_zerodha_health)

    # Mock provider health (should always be healthy)
    def t_mock_health():
        r = get("/providers/mock/health")
        assert r.status_code == 200
        assert r.json()["healthy"], "mock should always be healthy"
    test("Mock provider health", t_mock_health)

    # Login URL
    def t_login_url():
        r = get("/auth/login-url")
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        d = r.json()
        url = d["login_url"]
        assert "kite.zerodha.com" in url, f"unexpected URL: {url}"
        assert "api_key=" in url, "missing api_key in URL"
        assert d["provider"] == "zerodha"
        print(f"    → Login URL: {url}")
    test("Auth login URL returns Kite URL", t_login_url)

    # Session status (before auth)
    def t_session():
        r = get("/auth/session")
        assert r.status_code == 200
        d = r.json()
        print(f"    → authenticated={d['authenticated']}")
    test("Auth session check", t_session)

    # Config (check secrets are redacted)
    def t_config():
        r = get("/config/")
        assert r.status_code == 200
        d = r.json()
        for key, val in d.items():
            if "api_key" in key.lower() or "api_secret" in key.lower():
                assert val == "********", f"SECURITY: {key} not redacted: {val}"
    test("Config endpoint redacts secrets", t_config)

    # Risk limits
    def t_risk():
        r = get("/config/risk/limits")
        assert r.status_code == 200
        d = r.json()
        assert "max_order_value" in d
        assert "max_daily_loss" in d
        assert "kill_switch_active" in d
    test("Risk limits endpoint", t_risk)

    # Risk status
    def t_risk_status():
        r = get("/config/risk/status")
        assert r.status_code == 200
        d = r.json()
        assert "daily_pnl" in d
    test("Risk status endpoint", t_risk_status)

    # Strategy types
    def t_strat_types():
        r = get("/strategies/types")
        assert r.status_code == 200
        types = r.json()
        names = [t["name"] for t in types]
        assert "sma_crossover" in names
        assert "rsi_mean_reversion" in names
    test("Strategy types list", t_strat_types)

    # Strategy list (empty)
    def t_strats():
        r = get("/strategies/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
    test("Strategy instances list", t_strats)


# ─────────────────────────────────────────────────────────────
#  PHASE 2: Authentication (exchange request_token)
# ─────────────────────────────────────────────────────────────

def test_phase2(request_token: str):
    print(f"\n{BOLD}═══ PHASE 2: Authentication (exchanging request_token) ═══{RESET}\n")

    def t_callback():
        r = post("/auth/callback", json={"request_token": request_token})
        if r.status_code == 200:
            d = r.json()
            print(f"    → Logged in as: {d['user_id']} ({d['user_name']})")
            print(f"    → Email: {d['email']}")
            print(f"    → Broker: {d['broker']}")
            print(f"    → Access token obtained ✓")
            return True
        elif r.status_code == 401:
            detail = r.json().get("detail", "")
            if "expired" in detail.lower() or "invalid" in detail.lower():
                print(f"    → Token error: {detail}")
                print(f"    → Tokens expire quickly. Please login again and retry immediately.")
            else:
                print(f"    → Auth failed: {detail}")
            return f"status={r.status_code}: {detail}"
        else:
            return f"status={r.status_code}: {r.text}"
    test("Exchange request_token for session", t_callback)

    # Verify session
    def t_session():
        r = get("/auth/session")
        assert r.status_code == 200
        d = r.json()
        if d["authenticated"]:
            print(f"    → Latency: {d['latency_ms']:.1f}ms")
        else:
            return "Session not authenticated after callback"
    test("Session authenticated after login", t_session)

    # Health check
    def t_health():
        r = get("/providers/zerodha/health")
        assert r.status_code == 200
        d = r.json()
        if d["healthy"]:
            print(f"    → Connected! Latency: {d['latency_ms']:.1f}ms")
        else:
            return f"Unhealthy: {d['message']}"
    test("Zerodha health check after auth", t_health)


# ─────────────────────────────────────────────────────────────
#  PHASE 3: Authenticated API tests
# ─────────────────────────────────────────────────────────────

def test_phase3():
    print(f"\n{BOLD}═══ PHASE 3: Authenticated API Tests ═══{RESET}\n")

    # First verify we're authenticated
    r = get("/auth/session")
    if r.status_code != 200 or not r.json().get("authenticated"):
        print(f"  {FAIL} Not authenticated. Run phase 2 first.")
        print(f"       1. Open the login URL in your browser")
        print(f"       2. Login to Zerodha")
        print(f"       3. Copy request_token from redirect URL")
        print(f"       4. Run: python test_zerodha_flow.py --request-token <TOKEN>")
        return

    print(f"  {BOLD}── Market Data ──{RESET}")

    # Quote
    def t_quote():
        r = get("/market/quote", params={"instruments": ["NSE:RELIANCE"]})
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        d = r.json()
        assert "NSE:RELIANCE" in d, f"missing NSE:RELIANCE: {list(d.keys())}"
        q = d["NSE:RELIANCE"]
        print(f"    → RELIANCE: ₹{q['last_price']} (O={q['ohlc_open']} H={q['ohlc_high']} L={q['ohlc_low']} C={q['ohlc_close']})")
    test("GET /market/quote NSE:RELIANCE", t_quote)

    # Multi-quote
    def t_multi_quote():
        instruments = ["NSE:RELIANCE", "NSE:TCS", "NSE:INFY"]
        r = get("/market/quote", params={"instruments": instruments})
        assert r.status_code == 200
        d = r.json()
        for inst in instruments:
            assert inst in d, f"missing {inst}"
        print(f"    → Fetched quotes for {len(d)} instruments")
    test("GET /market/quote multiple instruments", t_multi_quote)

    # LTP
    def t_ltp():
        r = get("/market/ltp", params={"instruments": ["NSE:RELIANCE", "NSE:INFY"]})
        assert r.status_code == 200
        d = r.json()
        for key, val in d.items():
            print(f"    → {key}: ₹{val.get('last_price', val)}")
    test("GET /market/ltp", t_ltp)

    # OHLC
    def t_ohlc():
        r = get("/market/ohlc", params={"instruments": ["NSE:RELIANCE"]})
        assert r.status_code == 200
        d = r.json()
        assert "NSE:RELIANCE" in d
    test("GET /market/ohlc", t_ohlc)

    # Instruments list
    def t_instruments():
        r = get("/market/instruments", params={"exchange": "NSE"})
        assert r.status_code == 200
        instruments = r.json()
        assert len(instruments) > 0, "No instruments returned"
        print(f"    → {len(instruments)} NSE instruments loaded")
        # Show a few examples
        for i in instruments[:3]:
            print(f"       {i['trading_symbol']:15s} {i.get('name', '')[:25]:25s} token={i['instrument_token']}")
    test("GET /market/instruments (NSE)", t_instruments)

    # Instrument search
    def t_search():
        r = get("/market/instruments/search", params={"q": "RELIANCE", "exchange": "NSE"})
        assert r.status_code == 200
        results = r.json()
        assert len(results) > 0, "No search results"
        symbols = [x["trading_symbol"] for x in results]
        assert "RELIANCE" in symbols, f"RELIANCE not in {symbols}"
        print(f"    → Found {len(results)} matches for 'RELIANCE'")
    test("GET /market/instruments/search", t_search)

    # Historical data
    def t_historical():
        # First find RELIANCE token
        r = get("/market/instruments/search", params={"q": "RELIANCE", "exchange": "NSE"})
        instruments = r.json()
        rel = next((i for i in instruments if i["trading_symbol"] == "RELIANCE"), None)
        if not rel:
            return "RELIANCE not found in instruments"
        token = rel["instrument_token"]
        
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        r = get(f"/market/historical/{token}", params={
            "interval": "day",
            "from_date": from_date,
            "to_date": to_date,
        })
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        candles = r.json()
        assert len(candles) > 0, "No historical candles"
        print(f"    → {len(candles)} daily candles for RELIANCE (token={token})")
        if candles:
            last = candles[-1]
            print(f"       Latest: {last['timestamp'][:10]} O={last['open']} H={last['high']} L={last['low']} C={last['close']} V={last['volume']}")
    test("GET /market/historical (RELIANCE daily)", t_historical)

    # Historical intraday
    def t_hist_intraday():
        r = get("/market/instruments/search", params={"q": "RELIANCE", "exchange": "NSE"})
        instruments = r.json()
        rel = next((i for i in instruments if i["trading_symbol"] == "RELIANCE"), None)
        if not rel:
            return "RELIANCE not found"
        token = rel["instrument_token"]
        
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        r = get(f"/market/historical/{token}", params={
            "interval": "5minute",
            "from_date": from_date,
            "to_date": to_date,
        })
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        candles = r.json()
        print(f"    → {len(candles)} 5-minute candles (last 5 days)")
    test("GET /market/historical (5min intraday)", t_hist_intraday)

    print(f"\n  {BOLD}── Portfolio ──{RESET}")

    # Orders
    def t_orders():
        r = get("/orders/")
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        orders = r.json()
        print(f"    → {len(orders)} orders today")
        for o in orders[:3]:
            print(f"       {o['order_id'][:12]}.. {o['trading_symbol']:12s} {o['transaction_type']:4s} qty={o['quantity']} status={o['status']}")
    test("GET /orders/", t_orders)

    # Positions
    def t_positions():
        r = get("/portfolio/positions")
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        d = r.json()
        net = d.get("net", [])
        print(f"    → {len(net)} net positions")
        for p in net[:3]:
            print(f"       {p['trading_symbol']:12s} qty={p['quantity']:+d} avg={p['average_price']:.2f} pnl={p.get('pnl', 0):.2f}")
    test("GET /portfolio/positions", t_positions)

    # Holdings
    def t_holdings():
        r = get("/portfolio/holdings")
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        holdings = r.json()
        print(f"    → {len(holdings)} holdings")
        for h in holdings[:5]:
            print(f"       {h['trading_symbol']:12s} qty={h['quantity']} avg={h.get('average_price', 0):.2f} ltp={h.get('last_price', 0):.2f}")
    test("GET /portfolio/holdings", t_holdings)

    # Margins
    def t_margins():
        r = get("/portfolio/margins")
        assert r.status_code == 200, f"status={r.status_code}: {r.text}"
        d = r.json()
        eq = d.get("equity", {})
        print(f"    → Equity: available=₹{eq.get('available_cash', 0):,.2f} net=₹{eq.get('net', 0):,.2f}")
    test("GET /portfolio/margins", t_margins)

    # Trades
    def t_trades():
        r = get("/orders/trades")
        if r.status_code == 200:
            trades = r.json()
            print(f"    → {len(trades)} trades today")
        elif r.status_code == 404:
            return "skip"  # endpoint might not exist
        else:
            return f"status={r.status_code}"
    test("GET /orders/trades", t_trades)

    print(f"\n  {BOLD}── Config & Risk ──{RESET}")

    # Config
    def t_config_all():
        r = get("/config/")
        assert r.status_code == 200
        d = r.json()
        print(f"    → {len(d)} config keys loaded")
    test("GET /config/", t_config_all)

    # Risk limits
    def t_risk_limits():
        r = get("/config/risk/limits")
        assert r.status_code == 200
        d = r.json()
        print(f"    → max_order_value=₹{d['max_order_value']:,.0f} max_daily_loss=₹{d['max_daily_loss']:,.0f}")
    test("GET /config/risk/limits", t_risk_limits)

    # Risk status
    def t_risk_status():
        r = get("/config/risk/status")
        assert r.status_code == 200
        d = r.json()
        print(f"    → daily_pnl=₹{d['daily_pnl']:,.2f} kill_switch={d['kill_switch_active']}")
    test("GET /config/risk/status", t_risk_status)


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────

def print_summary():
    total = results["passed"] + results["failed"] + results["skipped"]
    print(f"\n{BOLD}═══ Summary ═══{RESET}")
    print(f"  Total:   {total}")
    print(f"  {PASS} Passed:  {results['passed']}")
    if results["failed"]:
        print(f"  {FAIL} Failed:  {results['failed']}")
    if results["skipped"]:
        print(f"  {WARN} Skipped: {results['skipped']}")
    print()
    if results["failed"] == 0:
        print(f"  {BOLD}{PASS} All tests passed!{RESET}")
    else:
        print(f"  {BOLD}{FAIL} Some tests failed.{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Test Zerodha API flow against running server")
    parser.add_argument("--request-token", "-t", help="Request token from Zerodha OAuth redirect")
    parser.add_argument("--authenticated", "-a", action="store_true", help="Run authenticated tests (assumes session already active)")
    parser.add_argument("--all", action="store_true", help="Run all phases")
    args = parser.parse_args()

    print(f"\n{BOLD}Zerodha Integration Test Suite{RESET}")
    print(f"Server: {BASE}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Check server is running
    try:
        r = requests.get(f"{BASE}/health", timeout=3)
        assert r.status_code == 200
    except Exception:
        print(f"\n{FAIL} Server not running at {BASE}")
        print(f"   Start it with: cd backend && .venv/bin/uvicorn app.main:app --port 8000")
        sys.exit(1)

    # Always run phase 1
    test_phase1()

    # Phase 2: authenticate with request_token
    if args.request_token:
        test_phase2(args.request_token)
        # If auth succeeded, also run phase 3
        r = get("/auth/session")
        if r.status_code == 200 and r.json().get("authenticated"):
            test_phase3()
    elif args.authenticated or args.all:
        # Check if already authenticated
        r = get("/auth/session")
        if r.status_code == 200 and r.json().get("authenticated"):
            test_phase3()
        else:
            print(f"\n{WARN} Not authenticated. To complete the flow:")
            print(f"   1. Open this URL in your browser:")
            login_r = get("/auth/login-url")
            if login_r.status_code == 200:
                print(f"      {login_r.json()['login_url']}")
            print(f"   2. Login with your Zerodha credentials")
            print(f"   3. Copy the request_token from the redirect URL")
            print(f"   4. Run: python test_zerodha_flow.py --request-token <TOKEN>")
    else:
        # Check auth status and give guidance
        r = get("/auth/session")
        if r.status_code == 200 and r.json().get("authenticated"):
            print(f"\n{PASS} Already authenticated! Running all tests...")
            test_phase3()
        else:
            print(f"\n{WARN} To test authenticated endpoints:")
            print(f"   1. Open this URL in your browser:")
            login_r = get("/auth/login-url")
            if login_r.status_code == 200:
                url = login_r.json()["login_url"]
                print(f"      {url}")
            print(f"   2. Login with your Zerodha credentials")
            print(f"   3. After redirect, copy the request_token from the URL bar")
            print(f"      (it looks like: localhost:8000/api/auth/redirect?request_token=XXXXX&status=success)")
            print(f"   4. Run: python test_zerodha_flow.py --request-token <TOKEN>")
            print(f"   5. Or if already logged in: python test_zerodha_flow.py --authenticated")

    print_summary()
    sys.exit(1 if results["failed"] else 0)


if __name__ == "__main__":
    main()
