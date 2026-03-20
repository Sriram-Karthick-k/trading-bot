/**
 * Tests for the API client module.
 */

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

import { health, orders, portfolio, auth, config, mock, strategies, providers, market, engine } from "@/lib/api";

beforeEach(() => {
  mockFetch.mockReset();
});

function mockResponse(data: unknown, status = 200) {
  mockFetch.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  });
}

describe("health.check()", () => {
  it("calls /api/health", async () => {
    mockResponse({ status: "ok", version: "0.1.0" });
    const result = await health.check();
    expect(result).toEqual({ status: "ok", version: "0.1.0" });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/health",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });
});

describe("auth", () => {
  it("getLoginUrl calls GET /auth/login-url", async () => {
    mockResponse({ login_url: "https://example.com", provider: "mock" });
    const result = await auth.getLoginUrl();
    expect(result.login_url).toBe("https://example.com");
  });

  it("callback calls POST /auth/callback", async () => {
    mockResponse({ user_id: "U1", access_token: "tok" });
    await auth.callback("test_token");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/auth/callback",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ request_token: "test_token" }),
      }),
    );
  });

  it("getSession calls GET /auth/session", async () => {
    mockResponse({ authenticated: true, latency_ms: 10 });
    const r = await auth.getSession();
    expect(r.authenticated).toBe(true);
  });
});

describe("orders", () => {
  it("getAll calls GET /orders/", async () => {
    mockResponse([]);
    const result = await orders.getAll();
    expect(result).toEqual([]);
  });

  it("place sends POST with order data", async () => {
    mockResponse({ order_id: "ORD1" });
    await orders.place({
      exchange: "NSE",
      trading_symbol: "RELIANCE",
      transaction_type: "BUY",
      order_type: "MARKET",
      quantity: 1,
      product: "CNC",
    });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/orders/place",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("cancel sends DELETE", async () => {
    mockResponse({ order_id: "ORD1", status: "cancelled" });
    await orders.cancel("regular", "ORD1");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/orders/regular/ORD1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("portfolio", () => {
  it("getPositions calls /portfolio/positions", async () => {
    mockResponse({ net: [], day: [] });
    const r = await portfolio.getPositions();
    expect(r.net).toEqual([]);
  });

  it("getHoldings calls /portfolio/holdings", async () => {
    mockResponse([]);
    const r = await portfolio.getHoldings();
    expect(r).toEqual([]);
  });

  it("getMargins calls /portfolio/margins", async () => {
    mockResponse({ equity: null, commodity: null });
    const r = await portfolio.getMargins();
    expect(r).toBeDefined();
  });
});

describe("strategies", () => {
  it("list returns strategy snapshots", async () => {
    mockResponse([{ strategy_id: "s1", state: "idle" }]);
    const r = await strategies.list();
    expect(r[0].strategy_id).toBe("s1");
  });

  it("start sends POST", async () => {
    mockResponse({ status: "started" });
    await strategies.start("s1");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/strategies/s1/start",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("stop sends POST", async () => {
    mockResponse({ status: "stopped" });
    await strategies.stop("s1");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/strategies/s1/stop",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("updateParams sends PUT", async () => {
    mockResponse({ status: "updated" });
    await strategies.updateParams("s1", { threshold: 100 });
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/strategies/s1/params",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});

describe("providers", () => {
  it("list returns provider info", async () => {
    mockResponse([{ name: "mock", is_active: true }]);
    const r = await providers.list();
    expect(r[0].name).toBe("mock");
  });

  it("activate sends POST", async () => {
    mockResponse({ active_provider: "mock" });
    await providers.activate("mock");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/providers/activate",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("config", () => {
  it("getRiskLimits calls /config/risk/limits", async () => {
    mockResponse({ max_order_value: 500000, kill_switch_active: false });
    const r = await config.getRiskLimits();
    expect(r.max_order_value).toBe(500000);
  });

  it("activateKillSwitch sends POST", async () => {
    mockResponse({ kill_switch_active: true });
    await config.activateKillSwitch();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/config/risk/kill-switch/activate",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("mock", () => {
  it("createSession sends POST with capital", async () => {
    mockResponse({ session_id: "id1", status: "created" });
    await mock.createSession(500000, "2025-01-01");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/mock/session",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("setSpeed sends POST", async () => {
    mockResponse({ speed: 10 });
    await mock.setSpeed(10);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/mock/time/speed",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("pause sends POST", async () => {
    mockResponse({ paused: true });
    await mock.pause();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/mock/time/pause",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("reset sends POST", async () => {
    mockResponse({ status: "reset" });
    await mock.reset();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/mock/reset",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("market", () => {
  it("getQuote builds query params correctly", async () => {
    mockResponse({});
    await market.getQuote(["NSE:RELIANCE"]);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("instruments=NSE%3ARELIANCE"),
      expect.any(Object),
    );
  });

  it("getHistorical builds URL with params", async () => {
    mockResponse([]);
    await market.getHistorical(256265, "day", "2025-01-01", "2025-01-31");
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining("/market/historical/256265"),
      expect.any(Object),
    );
  });
});

describe("error handling", () => {
  it("throws ApiError on non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: () => Promise.resolve("Not found"),
    });
    await expect(health.check()).rejects.toThrow("Not found");
  });
});

describe("engine", () => {
  it("getStatus calls GET /engine/status", async () => {
    mockResponse({
      state: "idle",
      picks_count: 0,
      strategies_count: 0,
      ticker_connected: false,
      started_at: null,
      stopped_at: null,
      metrics: { total_signals: 0, total_orders: 0, total_fills: 0, session_pnl: 0 },
      strategies: {},
      recent_events: [],
    });
    const r = await engine.getStatus();
    expect(r.state).toBe("idle");
    expect(r.picks_count).toBe(0);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/status",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("loadPicks sends POST with picks array", async () => {
    mockResponse({ status: "loaded", picks_count: 2, symbols: ["RELIANCE", "TCS"] });
    const picks = [
      {
        trading_symbol: "RELIANCE",
        instrument_token: 256265,
        exchange: "NSE",
        direction: "LONG",
        today_open: 2500,
        prev_close: 2480,
        quantity: 1,
        cpr: { pivot: 2490, tc: 2495, bc: 2485, width: 10, width_pct: 0.4 },
      },
      {
        trading_symbol: "TCS",
        instrument_token: 2953217,
        cpr: { pivot: 3500, tc: 3510, bc: 3490, width: 20, width_pct: 0.57 },
      },
    ];
    const r = await engine.loadPicks(picks);
    expect(r.picks_count).toBe(2);
    expect(r.symbols).toEqual(["RELIANCE", "TCS"]);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/load-picks",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("start sends POST /engine/start", async () => {
    mockResponse({ status: "started", state: "running", strategies: 3 });
    const r = await engine.start();
    expect(r.status).toBe("started");
    expect(r.strategies).toBe(3);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/start",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("stop sends POST /engine/stop", async () => {
    mockResponse({ status: "stopped", state: "stopped" });
    const r = await engine.stop();
    expect(r.status).toBe("stopped");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/stop",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("pause sends POST /engine/pause", async () => {
    mockResponse({ status: "paused", state: "paused" });
    const r = await engine.pause();
    expect(r.status).toBe("paused");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/pause",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("resume sends POST /engine/resume", async () => {
    mockResponse({ status: "resumed", state: "running" });
    const r = await engine.resume();
    expect(r.status).toBe("resumed");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/resume",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("getPicks calls GET /engine/picks", async () => {
    mockResponse([
      {
        trading_symbol: "RELIANCE",
        instrument_token: 256265,
        exchange: "NSE",
        direction: "LONG",
        quantity: 1,
        today_open: 2500,
        prev_close: 2480,
        cpr: { pivot: 2490, tc: 2495, bc: 2485, width: 10, width_pct: 0.4 },
      },
    ]);
    const r = await engine.getPicks();
    expect(r).toHaveLength(1);
    expect(r[0].trading_symbol).toBe("RELIANCE");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/picks",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("getEvents calls GET /engine/events with limit", async () => {
    mockResponse([
      { timestamp: "2025-01-01T09:15:00", type: "info", message: "Engine started", data: {} },
    ]);
    const r = await engine.getEvents(10);
    expect(r).toHaveLength(1);
    expect(r[0].type).toBe("info");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/events?limit=10",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("getEvents calls GET /engine/events without limit", async () => {
    mockResponse([]);
    await engine.getEvents();
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/events",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it("feedCandle sends POST /engine/feed-candle", async () => {
    mockResponse({ status: "fed", instrument_token: 256265 });
    const r = await engine.feedCandle({
      instrument_token: 256265,
      timestamp: "2025-01-01T09:20:00",
      open: 2500,
      high: 2510,
      low: 2495,
      close: 2508,
      volume: 1000,
    });
    expect(r.status).toBe("fed");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/engine/feed-candle",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
