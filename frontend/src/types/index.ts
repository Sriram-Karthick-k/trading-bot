/**
 * Shared types matching the backend API responses.
 */

export interface ParamSchema {
  name: string;
  type: "int" | "float" | "string" | "bool" | "enum";
  default: unknown;
  label: string;
  description: string;
  min_value?: number | null;
  max_value?: number | null;
  enum_values?: string[] | null;
  required: boolean;
}

export interface StrategyType {
  name: string;
  description: string;
  params_schema: ParamSchema[];
}

export interface Instrument {
  instrument_token: number;
  exchange_token: number;
  trading_symbol: string;
  name: string;
  exchange: string;
  instrument_type?: string;
  segment?: string;
  lot_size: number;
  tick_size: number;
  last_price?: number;
  expiry?: string;
  strike?: number;
}

export interface Order {
  order_id: string;
  exchange_order_id?: string;
  exchange: string;
  trading_symbol: string;
  transaction_type: "BUY" | "SELL";
  order_type: string;
  product: string;
  quantity: number;
  filled_quantity: number;
  pending_quantity: number;
  price?: number;
  trigger_price?: number;
  average_price: number;
  status: string;
  status_message?: string;
  placed_at?: string;
}

export interface Position {
  trading_symbol: string;
  exchange: string;
  product: string;
  quantity: number;
  average_price: number;
  last_price: number;
  pnl: number;
  buy_quantity?: number;
  sell_quantity?: number;
  buy_price?: number;
  sell_price?: number;
  multiplier?: number;
}

export interface Holding {
  trading_symbol: string;
  exchange: string;
  isin?: string;
  quantity: number;
  t1_quantity?: number;
  average_price: number;
  last_price: number;
  pnl: number;
  day_change?: number;
  day_change_percentage?: number;
}

export interface Quote {
  instrument_token: number;
  last_price: number;
  ohlc_open: number;
  ohlc_high: number;
  ohlc_low: number;
  ohlc_close: number;
  volume: number;
  oi?: number;
  last_quantity?: number;
  average_price?: number;
  buy_quantity?: number;
  sell_quantity?: number;
  net_change?: number;
  lower_circuit?: number;
  upper_circuit?: number;
  timestamp?: string;
}

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  oi?: number;
}

export interface ProviderInfo {
  name: string;
  display_name: string;
  is_active: boolean;
  supported_exchanges: string[];
  supports_websocket: boolean;
}

export interface StrategySnapshot {
  strategy_id: string;
  name: string;
  state: "idle" | "running" | "paused" | "stopped" | "error";
  params: Record<string, unknown>;
  metrics: StrategyMetrics;
  subscribed_instruments: number[];
  pending_signals: number;
}

export interface StrategyMetrics {
  total_signals: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  total_pnl: number;
  max_drawdown: number;
  sharpe_ratio: number;
}

export interface RiskStatus {
  kill_switch_active: boolean;
  daily_pnl: number;
  daily_loss: number;
  daily_loss_limit: number;
  daily_loss_remaining: number;
  orders_last_minute: number;
  order_rate_limit: number;
}

export interface RiskLimits {
  max_order_value: number;
  max_position_value: number;
  max_loss_per_trade: number;
  max_daily_loss: number;
  max_open_orders: number;
  max_open_positions: number;
  max_quantity_per_order: number;
  max_orders_per_minute: number;
  kill_switch_active: boolean;
}

export interface MockSessionStatus {
  virtual_capital: number;
  current_time: string;
  is_market_open: boolean;
  progress: number;
  speed: number;
  paused: boolean;
  open_orders: number;
  positions: number;
  total_pnl: number;
}

export interface Margins {
  equity?: {
    available_cash: number;
    used_margin: number;
    available_margin: number;
  };
  commodity?: {
    available_cash: number;
    used_margin: number;
    available_margin: number;
  };
}

// ── Trading Mode Types ─────────────────────────────────────

export type TradingMode = "live" | "paper";

export interface TradingModeResponse {
  mode: TradingMode;
  is_paper: boolean;
}

export interface TradingModeSwitchResult {
  mode: TradingMode;
  is_paper: boolean;
  message: string;
}

export interface PaperStatus {
  initial_capital: number;
  available_capital: number;
  total_orders: number;
  total_fills: number;
  open_positions: number;
  realised_pnl: number;
  total_brokerage: number;
}

export interface TradingModeStatus {
  mode: TradingMode;
  is_paper: boolean;
  paper_status: PaperStatus | null;
}

// ── Engine Types ────────────────────────────────────────────

export type EngineState =
  | "idle"
  | "loading"
  | "running"
  | "paused"
  | "stopping"
  | "stopped"
  | "error";

export interface EngineCPR {
  pivot: number;
  tc: number;
  bc: number;
  width_pct: number;
}

export interface EngineStrategyMetrics {
  total_signals: number;
  total_trades: number;
  total_pnl: number;
}

export interface EngineStrategyDetail {
  strategy_id: string;
  symbol: string;
  state: string;
  direction: string;
  cpr: EngineCPR | null;
  metrics: EngineStrategyMetrics;
  position: string | null;
  entry_price: number;
  stop_loss: number;
  target: number;
  traded_today: boolean;
}

export interface EngineEvent {
  timestamp: string;
  type: string;
  message: string;
  data: Record<string, unknown>;
}

export interface EngineStatus {
  state: EngineState;
  picks_count: number;
  strategies_count: number;
  ticker_connected: boolean;
  is_paper: boolean;
  started_at: string | null;
  stopped_at: string | null;
  metrics: {
    total_signals: number;
    total_orders: number;
    total_fills: number;
    session_pnl: number;
  };
  strategies: Record<string, EngineStrategyDetail>;
  recent_events: EngineEvent[];
}

export interface EnginePick {
  trading_symbol: string;
  instrument_token: number;
  exchange: string;
  direction: string;
  quantity: number;
  today_open: number;
  prev_close: number;
  cpr: {
    pivot: number;
    tc: number;
    bc: number;
    width: number;
    width_pct: number;
  };
}

// ── Trade Journal Types ────────────────────────────────────

export interface JournalTrade {
  trade_id: string;
  order_id: string;
  strategy_id: string;
  trading_symbol: string;
  exchange: string;
  direction: "LONG" | "SHORT";
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  entry_time: string | null;
  exit_time: string | null;
  stop_loss: number;
  target: number;
  exit_reason: string;
  is_open: boolean;
  duration_minutes: number | null;
  risk_reward_actual: number | null;
  is_paper: boolean;
}

export interface JournalTradesResponse {
  trades: JournalTrade[];
  total: number;
  returned: number;
}

export interface DailyPnL {
  date: string;
  total_pnl: number;
  realized_pnl: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  largest_win: number;
  largest_loss: number;
  total_brokerage: number;
  net_pnl: number;
  is_paper: boolean;
}

export interface DailyPnLResponse {
  daily_pnl: DailyPnL[];
  total_days: number;
  cumulative_pnl: number;
}

export interface PerformanceSummary {
  total_trading_days: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_daily_pnl: number;
  best_day_pnl: number;
  worst_day_pnl: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  avg_trade_pnl: number;
  avg_winner: number;
  avg_loser: number;
  profit_factor: number;
  max_drawdown: number;
  sharpe_ratio: number;
  avg_trade_duration_min: number;
}

export interface SessionSummary {
  mode: string;
  is_paper: boolean;
  engine_state: string;
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  session_pnl: number;
  today_pnl: DailyPnL | null;
  performance: PerformanceSummary;
}
