/**
 * API client for backend communication.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}/api${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, text);
  }

  return res.json();
}

// ── Auth ────────────────────────────────────────────────

export const auth = {
  getLoginUrl: () => request<{ login_url: string; provider: string }>("/auth/login-url"),
  callback: (requestToken: string) =>
    request("/auth/callback", {
      method: "POST",
      body: JSON.stringify({ request_token: requestToken }),
    }),
  getSession: () => request<{ authenticated: boolean; latency_ms: number | null }>("/auth/session"),
};

// ── Orders ──────────────────────────────────────────────

export const orders = {
  place: (order: {
    exchange: string;
    trading_symbol: string;
    transaction_type: string;
    order_type: string;
    quantity: number;
    product: string;
    price?: number;
    trigger_price?: number;
  }) =>
    request<{ order_id: string }>("/orders/place", {
      method: "POST",
      body: JSON.stringify(order),
    }),
  getAll: () => request<import("@/types").Order[]>("/orders/"),
  cancel: (variety: string, orderId: string) =>
    request(`/orders/${variety}/${orderId}`, { method: "DELETE" }),
};

// ── Portfolio ───────────────────────────────────────────

export const portfolio = {
  getPositions: () =>
    request<{ net: import("@/types").Position[]; day: import("@/types").Position[] }>(
      "/portfolio/positions",
    ),
  getHoldings: () => request<import("@/types").Holding[]>("/portfolio/holdings"),
  getMargins: () => request<import("@/types").Margins>("/portfolio/margins"),
};

// ── Market ──────────────────────────────────────────────

export const market = {
  getQuote: (instruments: string[]) => {
    const params = instruments.map((i) => `instruments=${encodeURIComponent(i)}`).join("&");
    return request<Record<string, import("@/types").Quote>>(`/market/quote?${params}`);
  },
  getLtp: (instruments: string[]) => {
    const params = instruments.map((i) => `instruments=${encodeURIComponent(i)}`).join("&");
    return request<Record<string, number>>(`/market/ltp?${params}`);
  },
  getHistorical: (token: number, interval: string, from: string, to: string) =>
    request<import("@/types").Candle[]>(
      `/market/historical/${token}?interval=${interval}&from_date=${from}&to_date=${to}`,
    ),
  getInstruments: (exchange?: string) =>
    request<import("@/types").Instrument[]>(
      `/market/instruments${exchange ? `?exchange=${encodeURIComponent(exchange)}` : ""}`,
    ),
  searchInstruments: (query: string, exchange?: string) => {
    const params = new URLSearchParams({ q: query });
    if (exchange) params.set("exchange", exchange);
    return request<import("@/types").Instrument[]>(`/market/instruments/search?${params}`);
  },
};

// ── Strategies ──────────────────────────────────────────

export const strategies = {
  list: () => request<import("@/types").StrategySnapshot[]>("/strategies/"),
  get: (id: string) => request<import("@/types").StrategySnapshot>(`/strategies/${id}`),
  types: () => request<import("@/types").StrategyType[]>("/strategies/types"),
  create: (strategyType: string, strategyId: string, params: Record<string, unknown>) =>
    request<import("@/types").StrategySnapshot>("/strategies/", {
      method: "POST",
      body: JSON.stringify({ strategy_type: strategyType, strategy_id: strategyId, params }),
    }),
  start: (id: string) => request(`/strategies/${id}/start`, { method: "POST" }),
  stop: (id: string) => request(`/strategies/${id}/stop`, { method: "POST" }),
  pause: (id: string) => request(`/strategies/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request(`/strategies/${id}/resume`, { method: "POST" }),
  updateParams: (id: string, params: Record<string, unknown>) =>
    request(`/strategies/${id}/params`, {
      method: "PUT",
      body: JSON.stringify({ params }),
    }),
  delete: (id: string) => request(`/strategies/${id}`, { method: "DELETE" }),
};

// ── Providers ───────────────────────────────────────────

export const providers = {
  list: () => request<import("@/types").ProviderInfo[]>("/providers/"),
  discover: () => request("/providers/discover", { method: "POST" }),
  activate: (name: string) =>
    request("/providers/activate", {
      method: "POST",
      body: JSON.stringify({ provider_name: name }),
    }),
  deactivate: () => request("/providers/deactivate", { method: "POST" }),
  getActive: () => request<{ name: string } | { active_provider: null }>("/providers/active"),
  health: (name: string) =>
    request<{ healthy: boolean; latency_ms: number; message: string }>(
      `/providers/${name}/health`,
    ),
};

// ── Config / Risk ───────────────────────────────────────

export const config = {
  getAll: () => request<Record<string, unknown>>("/config/"),
  get: (key: string) => request<{ key: string; value: unknown }>(`/config/${key}`),
  set: (key: string, value: string) =>
    request("/config/", {
      method: "PUT",
      body: JSON.stringify({ key, value }),
    }),
  getRiskLimits: () => request<import("@/types").RiskLimits>("/config/risk/limits"),
  updateRiskLimits: (limits: Partial<import("@/types").RiskLimits>) =>
    request("/config/risk/limits", {
      method: "PUT",
      body: JSON.stringify(limits),
    }),
  getRiskStatus: () => request<import("@/types").RiskStatus>("/config/risk/status"),
  activateKillSwitch: () =>
    request("/config/risk/kill-switch/activate", { method: "POST" }),
  deactivateKillSwitch: () =>
    request("/config/risk/kill-switch/deactivate", { method: "POST" }),
};

// ── Mock ────────────────────────────────────────────────

export const mock = {
  createSession: (capital: number, startDate?: string, endDate?: string) =>
    request("/mock/session", {
      method: "POST",
      body: JSON.stringify({
        initial_capital: capital,
        start_date: startDate,
        end_date: endDate,
      }),
    }),
  getStatus: () => request<import("@/types").MockSessionStatus>("/mock/session"),
  loadSampleData: () => request<{ instruments_loaded: number; symbols: string[] }>("/mock/sample-data", { method: "POST" }),
  getInstruments: () => request<{ symbol: string; token: number; name: string; ltp: number; exchange: string }[]>("/mock/instruments"),
  setDate: (date: string) =>
    request("/mock/time/set-date", {
      method: "POST",
      body: JSON.stringify({ date }),
    }),
  marketOpen: () => request("/mock/time/market-open", { method: "POST" }),
  marketClose: () => request("/mock/time/market-close", { method: "POST" }),
  nextDay: () => request("/mock/time/next-day", { method: "POST" }),
  setSpeed: (speed: number) =>
    request("/mock/time/speed", {
      method: "POST",
      body: JSON.stringify({ speed }),
    }),
  pause: () => request("/mock/time/pause", { method: "POST" }),
  resume: () => request("/mock/time/resume", { method: "POST" }),
  reset: () => request("/mock/reset", { method: "POST" }),
  getOrders: () => request<import("@/types").Order[]>("/mock/orders"),
  getPositions: () =>
    request<{ net: import("@/types").Position[] }>("/mock/positions"),
};

// ── Health ──────────────────────────────────────────────

export const health = {
  check: () => request<{ status: string; version: string }>("/health"),
};

// ── Backtest ────────────────────────────────────────────

export interface BacktestParams {
  strategy_type: string;
  instrument_token: number;
  tradingsymbol: string;
  exchange?: string;
  interval?: string;
  from_date: string;
  to_date: string;
  initial_capital?: number;
  params?: Record<string, unknown>;
}

export interface BacktestTrade {
  timestamp: string;
  action: string;
  symbol: string;
  quantity: number;
  price: number;
  order_id: string;
  reason: string;
}

export interface BacktestResult {
  strategy: string;
  symbol: string;
  interval: string;
  from_date: string;
  to_date: string;
  data_source: string;
  initial_capital: number;
  final_capital: number;
  total_pnl: number;
  total_return_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  max_drawdown: number;
  total_signals: number;
  total_candles: number;
  trades: BacktestTrade[];
  equity_curve: { timestamp: string; equity: number; drawdown: number }[];
}

export const backtest = {
  run: (params: BacktestParams) =>
    request<BacktestResult>("/backtest/run", {
      method: "POST",
      body: JSON.stringify(params),
    }),
};
