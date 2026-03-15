"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import {
  backtest,
  market,
  type BacktestResult,
  type BacktestParams,
} from "@/lib/api";
import { formatCurrency, formatPnl } from "@/lib/utils";

/* ───────── Types ───────── */
interface StrategyType {
  name: string;
  description: string;
  params_schema: {
    name: string;
    type: string;
    default: unknown;
    label: string;
    description: string;
    min_value: number | null;
    max_value: number | null;
    required: boolean;
  }[];
}

interface SearchResult {
  instrument_token: number;
  trading_symbol: string;
  name: string;
  exchange: string;
  last_price: number;
}

/* ═══════ Page ═══════ */
export default function BacktestPage() {
  const [strategies, setStrategies] = useState<StrategyType[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>("");
  const [instrument, setInstrument] = useState<SearchResult | null>(null);
  const [interval, setInterval] = useState("day");
  const [fromDate, setFromDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 1);
    return d.toISOString().split("T")[0];
  });
  const [toDate, setToDate] = useState(
    () => new Date().toISOString().split("T")[0]
  );
  const [capital, setCapital] = useState(100000);
  const [strategyParams, setStrategyParams] = useState<Record<string, unknown>>(
    {}
  );
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load strategy types
  useEffect(() => {
    fetch("/api/strategies/types")
      .then((r) => r.json())
      .then((data) => {
        setStrategies(data);
        if (data.length > 0) setSelectedStrategy(data[0].name);
      })
      .catch(() => {});
  }, []);

  // Update params when strategy changes
  useEffect(() => {
    const strat = strategies.find((s) => s.name === selectedStrategy);
    if (!strat) return;
    const defaults: Record<string, unknown> = {};
    strat.params_schema.forEach((p) => {
      if (
        !["instrument_token", "trading_symbol", "exchange"].includes(p.name)
      ) {
        defaults[p.name] = p.default;
      }
    });
    setStrategyParams(defaults);
  }, [selectedStrategy, strategies]);

  const currentSchema = strategies.find(
    (s) => s.name === selectedStrategy
  )?.params_schema;

  const handleRun = async () => {
    if (!instrument || !selectedStrategy) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const params: BacktestParams = {
        strategy_type: selectedStrategy,
        instrument_token: instrument.instrument_token,
        tradingsymbol: instrument.trading_symbol,
        exchange: instrument.exchange,
        interval,
        from_date: fromDate,
        to_date: toDate,
        initial_capital: capital,
        params: {
          ...strategyParams,
          quantity: Number(strategyParams.quantity) || 1,
        },
      };
      const r = await backtest.run(params);
      setResult(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Backtest failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="p-8 space-y-6 max-w-[1400px]">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight">
          Strategy Backtester
        </h2>
        <p className="text-[var(--muted)] text-sm mt-1">
          Test strategies against real historical data from Zerodha to see how
          they would have performed
        </p>
      </div>

      {/* Config Panel */}
      <div className="card">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Strategy */}
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              Strategy
            </label>
            <select
              className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
              value={selectedStrategy}
              onChange={(e) => setSelectedStrategy(e.target.value)}
            >
              {strategies.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </option>
              ))}
            </select>
            <p className="text-xs text-[var(--muted)] mt-1">
              {strategies.find((s) => s.name === selectedStrategy)?.description}
            </p>
          </div>

          {/* Instrument */}
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              Instrument
            </label>
            <InstrumentSearch onSelect={setInstrument} selected={instrument} />
          </div>

          {/* Interval */}
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              Candle Interval
            </label>
            <select
              className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
              value={interval}
              onChange={(e) => setInterval(e.target.value)}
            >
              <option value="minute">1 Minute</option>
              <option value="5minute">5 Minutes</option>
              <option value="15minute">15 Minutes</option>
              <option value="60minute">1 Hour</option>
              <option value="day">Daily</option>
            </select>
          </div>

          {/* Date Range */}
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              From Date
            </label>
            <input
              type="date"
              className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              To Date
            </label>
            <input
              type="date"
              className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
            />
          </div>

          {/* Capital */}
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              Initial Capital
            </label>
            <input
              type="number"
              className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              min={1000}
              step={10000}
            />
          </div>
        </div>

        {/* Strategy Params */}
        {currentSchema && (
          <div className="mt-6 pt-6 border-t border-[var(--card-border)]">
            <h4 className="text-xs text-[var(--muted)] uppercase tracking-wider mb-3">
              Strategy Parameters
            </h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {currentSchema
                .filter(
                  (p) =>
                    !["instrument_token", "trading_symbol", "exchange"].includes(
                      p.name
                    )
                )
                .map((p) => (
                  <div key={p.name}>
                    <label className="block text-xs text-[var(--muted)] mb-1">
                      {p.label || p.name}
                    </label>
                    <input
                      type={p.type === "float" ? "number" : p.type === "int" ? "number" : "text"}
                      step={p.type === "float" ? 0.1 : 1}
                      min={p.min_value ?? undefined}
                      max={p.max_value ?? undefined}
                      className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-1.5 text-sm"
                      value={String(strategyParams[p.name] ?? p.default ?? "")}
                      onChange={(e) =>
                        setStrategyParams((prev) => ({
                          ...prev,
                          [p.name]:
                            p.type === "int"
                              ? parseInt(e.target.value) || 0
                              : p.type === "float"
                                ? parseFloat(e.target.value) || 0
                                : e.target.value,
                        }))
                      }
                    />
                    {p.description && (
                      <p className="text-[10px] text-[var(--muted)] mt-0.5">
                        {p.description}
                      </p>
                    )}
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Run Button */}
        <div className="mt-6 flex items-center gap-4">
          <button
            className="btn-primary px-8 py-2.5"
            onClick={handleRun}
            disabled={running || !instrument || !selectedStrategy}
          >
            {running ? (
              <span className="flex items-center gap-2">
                <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Running Backtest…
              </span>
            ) : (
              "▶ Run Backtest"
            )}
          </button>
          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>
      </div>

      {/* Results */}
      {result && <BacktestResults result={result} />}
    </div>
  );
}

/* ═══════ Instrument Search ═══════ */
function InstrumentSearch({
  onSelect,
  selected,
}: {
  onSelect: (i: SearchResult) => void;
  selected: SearchResult | null;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const search = useCallback((q: string) => {
    if (q.length < 1) {
      setResults([]);
      return;
    }
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      try {
        const data = await market.searchInstruments(q);
        setResults(data as unknown as SearchResult[]);
        setOpen(true);
      } catch {
        setResults([]);
      }
    }, 250);
  }, []);

  return (
    <div className="relative" ref={containerRef}>
      <input
        type="text"
        className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
        placeholder="Search stocks (e.g. RELIANCE, TCS)..."
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          search(e.target.value);
        }}
        onFocus={() => results.length > 0 && setOpen(true)}
      />
      {selected && (
        <div className="mt-1 text-xs text-emerald-400">
          ✓ {selected.exchange}:{selected.trading_symbol} — {selected.name}
        </div>
      )}
      {open && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-[var(--card)] border border-[var(--card-border)] rounded-lg shadow-xl max-h-60 overflow-auto">
          {results.map((r) => (
            <button
              key={r.instrument_token}
              className="w-full px-3 py-2 text-left text-sm hover:bg-white/5 flex justify-between items-center"
              onClick={() => {
                onSelect(r);
                setQuery(r.trading_symbol);
                setOpen(false);
              }}
            >
              <span>
                <span className="font-medium">{r.trading_symbol}</span>
                <span className="text-[var(--muted)] ml-2 text-xs">
                  {r.name}
                </span>
              </span>
              <span className="text-xs text-[var(--muted)]">
                {r.exchange} · ₹{r.last_price?.toFixed(2)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ═══════ Backtest Results ═══════ */
function BacktestResults({ result }: { result: BacktestResult }) {
  const [tab, setTab] = useState<"summary" | "trades" | "equity">("summary");

  const isProfit = result.total_pnl >= 0;

  return (
    <div className="space-y-4">
      {/* Data source banner */}
      <div
        className={`rounded-lg px-4 py-2 text-sm flex items-center gap-2 ${
          result.data_source === "zerodha"
            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
            : result.data_source === "mock_synthetic"
              ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
              : "bg-red-500/10 text-red-400 border border-red-500/20"
        }`}
      >
        {result.data_source === "zerodha" ? (
          <>
            <span>✓</span> Backtested with <strong>real Zerodha market data</strong>{" "}
            — {result.total_candles} candles
          </>
        ) : result.data_source === "mock_synthetic" ? (
          <>
            <span>⚠</span> Backtested with <strong>synthetic mock data</strong>{" "}
            — connect Zerodha for real results
          </>
        ) : (
          <>
            <span>✗</span> No data available for this instrument/period
          </>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCard
          label="Total P&L"
          value={formatPnl(result.total_pnl)}
          color={isProfit ? "text-emerald-400" : "text-red-400"}
          large
        />
        <StatCard
          label="Return"
          value={`${result.total_return_pct >= 0 ? "+" : ""}${result.total_return_pct}%`}
          color={isProfit ? "text-emerald-400" : "text-red-400"}
          large
        />
        <StatCard
          label="Final Capital"
          value={formatCurrency(result.final_capital)}
        />
        <StatCard label="Trades" value={String(result.total_trades)} />
        <StatCard
          label="Win Rate"
          value={`${result.win_rate}%`}
          color={result.win_rate >= 50 ? "text-emerald-400" : "text-amber-400"}
        />
        <StatCard
          label="Max Drawdown"
          value={`${result.max_drawdown}%`}
          color="text-red-400"
        />
      </div>

      {/* Tabs */}
      <div className="card">
        <div className="flex gap-1 mb-4 border-b border-[var(--card-border)] pb-2">
          {(["summary", "trades", "equity"] as const).map((t) => (
            <button
              key={t}
              className={`px-4 py-1.5 text-sm rounded-t-lg transition-colors ${
                tab === t
                  ? "text-white bg-white/10"
                  : "text-[var(--muted)] hover:text-white"
              }`}
              onClick={() => setTab(t)}
            >
              {t === "summary"
                ? "Summary"
                : t === "trades"
                  ? `Trades (${result.total_trades})`
                  : "Equity Curve"}
            </button>
          ))}
        </div>

        {tab === "summary" && <SummaryTab result={result} />}
        {tab === "trades" && <TradesTab result={result} />}
        {tab === "equity" && <EquityTab result={result} />}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color,
  large,
}: {
  label: string;
  value: string;
  color?: string;
  large?: boolean;
}) {
  return (
    <div className="card !p-4">
      <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
        {label}
      </p>
      <p
        className={`${large ? "text-xl" : "text-lg"} font-semibold mt-1 ${color || ""}`}
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {value}
      </p>
    </div>
  );
}

/* ═══════ Summary Tab ═══════ */
function SummaryTab({ result }: { result: BacktestResult }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-y-4 gap-x-8 text-sm">
      <Row label="Strategy" value={result.strategy.replace(/_/g, " ")} />
      <Row label="Symbol" value={`${result.symbol}`} />
      <Row label="Interval" value={result.interval} />
      <Row label="Period" value={`${result.from_date} → ${result.to_date}`} />
      <Row label="Data Source" value={result.data_source} />
      <Row label="Candles Processed" value={String(result.total_candles)} />
      <Row
        label="Initial Capital"
        value={formatCurrency(result.initial_capital)}
      />
      <Row
        label="Final Capital"
        value={formatCurrency(result.final_capital)}
      />
      <Row label="Total P&L" value={formatPnl(result.total_pnl)} />
      <Row
        label="Return"
        value={`${result.total_return_pct >= 0 ? "+" : ""}${result.total_return_pct}%`}
      />
      <Row label="Total Signals" value={String(result.total_signals)} />
      <Row label="Total Trades" value={String(result.total_trades)} />
      <Row label="Winning Trades" value={String(result.winning_trades)} />
      <Row label="Losing Trades" value={String(result.losing_trades)} />
      <Row label="Win Rate" value={`${result.win_rate}%`} />
      <Row label="Max Drawdown" value={`${result.max_drawdown}%`} />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between py-1 border-b border-[var(--card-border)]">
      <span className="text-[var(--muted)]">{label}</span>
      <span className="font-medium" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
        {value}
      </span>
    </div>
  );
}

/* ═══════ Trades Tab ═══════ */
function TradesTab({ result }: { result: BacktestResult }) {
  if (result.trades.length === 0) {
    return (
      <p className="text-[var(--muted)] text-sm py-8 text-center">
        No trades were executed during this backtest period.
        <br />
        <span className="text-xs">
          The strategy may need more data to generate signals, or the parameters
          may need tuning.
        </span>
      </p>
    );
  }

  return (
    <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-[var(--card)]">
          <tr className="text-[var(--muted)] text-xs uppercase tracking-wider">
            <th className="text-left py-2 pr-4">Time</th>
            <th className="text-left py-2 pr-4">Action</th>
            <th className="text-left py-2 pr-4">Symbol</th>
            <th className="text-right py-2 pr-4">Qty</th>
            <th className="text-right py-2 pr-4">Price</th>
            <th className="text-left py-2">Reason</th>
          </tr>
        </thead>
        <tbody>
          {result.trades.map((t, i) => (
            <tr
              key={i}
              className="border-t border-[var(--card-border)] hover:bg-white/5"
            >
              <td className="py-2 pr-4 text-[var(--muted)]">
                {new Date(t.timestamp).toLocaleDateString("en-IN", {
                  day: "2-digit",
                  month: "short",
                  year: "2-digit",
                })}
              </td>
              <td className="py-2 pr-4">
                <span
                  className={`px-2 py-0.5 rounded text-xs font-medium ${
                    t.action === "BUY"
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-red-500/10 text-red-400"
                  }`}
                >
                  {t.action}
                </span>
              </td>
              <td className="py-2 pr-4 font-medium">{t.symbol}</td>
              <td
                className="py-2 pr-4 text-right"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {t.quantity}
              </td>
              <td
                className="py-2 pr-4 text-right"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                ₹{t.price.toFixed(2)}
              </td>
              <td className="py-2 text-xs text-[var(--muted)] max-w-[300px] truncate">
                {t.reason}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ═══════ Equity Curve Tab ═══════ */
function EquityTab({ result }: { result: BacktestResult }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || result.equity_curve.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = rect.height;
    const PAD = { top: 30, right: 80, bottom: 40, left: 20 };

    const data = result.equity_curve;
    const equities = data.map((d) => d.equity);
    const minE = Math.min(...equities) * 0.998;
    const maxE = Math.max(...equities) * 1.002;

    const xScale = (i: number) =>
      PAD.left + (i / (data.length - 1)) * (W - PAD.left - PAD.right);
    const yScale = (v: number) =>
      PAD.top + (1 - (v - minE) / (maxE - minE)) * (H - PAD.top - PAD.bottom);

    // Background
    ctx.fillStyle = "#141414";
    ctx.fillRect(0, 0, W, H);

    // Grid lines
    ctx.strokeStyle = "#262626";
    ctx.lineWidth = 0.5;
    const gridLines = 5;
    for (let i = 0; i <= gridLines; i++) {
      const y = PAD.top + (i / gridLines) * (H - PAD.top - PAD.bottom);
      ctx.beginPath();
      ctx.moveTo(PAD.left, y);
      ctx.lineTo(W - PAD.right, y);
      ctx.stroke();
      // Label
      const val = maxE - (i / gridLines) * (maxE - minE);
      ctx.fillStyle = "#737373";
      ctx.font = "10px 'JetBrains Mono', monospace";
      ctx.textAlign = "left";
      ctx.fillText(`₹${(val / 1000).toFixed(1)}k`, W - PAD.right + 5, y + 3);
    }

    // Initial capital line
    const initY = yScale(result.initial_capital);
    ctx.strokeStyle = "#525252";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(PAD.left, initY);
    ctx.lineTo(W - PAD.right, initY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Fill under curve
    const gradient = ctx.createLinearGradient(0, PAD.top, 0, H - PAD.bottom);
    if (result.total_pnl >= 0) {
      gradient.addColorStop(0, "rgba(16, 185, 129, 0.15)");
      gradient.addColorStop(1, "rgba(16, 185, 129, 0)");
    } else {
      gradient.addColorStop(0, "rgba(239, 68, 68, 0.15)");
      gradient.addColorStop(1, "rgba(239, 68, 68, 0)");
    }
    ctx.beginPath();
    ctx.moveTo(xScale(0), H - PAD.bottom);
    data.forEach((_, i) => ctx.lineTo(xScale(i), yScale(equities[i])));
    ctx.lineTo(xScale(data.length - 1), H - PAD.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    // Equity line
    ctx.beginPath();
    data.forEach((_, i) => {
      const x = xScale(i);
      const y = yScale(equities[i]);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = result.total_pnl >= 0 ? "#10b981" : "#ef4444";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Trade markers
    result.trades.forEach((trade) => {
      const idx = data.findIndex((d) => d.timestamp === trade.timestamp);
      if (idx < 0) return;
      const x = xScale(idx);
      const y = yScale(equities[idx]);
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = trade.action === "BUY" ? "#10b981" : "#ef4444";
      ctx.fill();
    });

    // X axis labels
    const labelCount = Math.min(6, data.length);
    ctx.fillStyle = "#737373";
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    for (let i = 0; i < labelCount; i++) {
      const idx = Math.floor((i / (labelCount - 1)) * (data.length - 1));
      const d = new Date(data[idx].timestamp);
      ctx.fillText(
        d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
        xScale(idx),
        H - PAD.bottom + 20
      );
    }
  }, [result]);

  return (
    <div>
      <canvas
        ref={canvasRef}
        className="w-full rounded-lg"
        style={{ height: "320px" }}
      />
      <p className="text-xs text-[var(--muted)] mt-2 text-center">
        Equity over time · Green/Red dots = Buy/Sell trades · Dashed line =
        Initial capital
      </p>
    </div>
  );
}
