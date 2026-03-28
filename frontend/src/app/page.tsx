"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  useOrders,
  usePositions,
  useRiskStatus,
  useStrategies,
  useEngineStatus,
  useEngineEvents,
  useTradingMode,
  useJournalTrades,
  usePerformance,
  useDecisionLogs,
} from "@/hooks/useData";
import { useEngineStream } from "@/hooks/useEngineStream";
import {
  auth,
  backtest,
  config,
  engine,
  type CPRScanParams,
  type CPRScanResult,
  type CPRStockEntry,
  type CPRIndexInfo,
} from "@/lib/api";
import type { EngineEvent, EngineStrategyDetail, JournalTrade } from "@/types";
import { formatCurrency, formatPnl, formatNumber, cn } from "@/lib/utils";

/* ═══════════════════════════════════════════════════════════════════════════
   CPR TRADING DESK — Simplified Single-Page Layout
   Flow: Header → Scanner → Engine (+ positions/orders) → Trade Journal
   ═══════════════════════════════════════════════════════════════════════════ */

export default function TradingCommandCenter() {
  const [authMsg, setAuthMsg] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const { data: tradingMode } = useTradingMode();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const authSuccess = params.get("auth");
    const authError = params.get("auth_error");
    const userId = params.get("user");

    if (authSuccess === "success" && userId) {
      setAuthMsg({ type: "success", text: `Logged in as ${userId}` });
      window.history.replaceState({}, "", "/");
    } else if (authError) {
      setAuthMsg({ type: "error", text: `Login failed: ${authError}` });
      window.history.replaceState({}, "", "/");
    }
  }, []);

  const isPaper = tradingMode?.is_paper ?? false;

  return (
    <div className="p-6 lg:p-8 space-y-5 max-w-[1800px] mx-auto">
      {/* Paper trading banner */}
      {isPaper && (
        <div className="bg-amber-500/10 border-2 border-amber-500/30 rounded-lg px-4 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <span className="text-amber-400 text-sm font-semibold">PAPER TRADING MODE</span>
            <span className="text-amber-400/60 text-xs">Simulated fills only — no real orders</span>
          </div>
          <a href="/settings" className="text-xs text-amber-400/80 hover:text-amber-300 transition-colors underline underline-offset-2">
            Switch to Live
          </a>
        </div>
      )}

      {/* Auth notification */}
      {authMsg && (
        <div
          className={cn(
            "rounded-lg px-4 py-3 flex items-center justify-between text-sm",
            authMsg.type === "success"
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
              : "bg-red-500/10 text-red-400 border border-red-500/30"
          )}
        >
          <span>
            {authMsg.type === "success" ? "+" : "x"} {authMsg.text}
          </span>
          <button
            onClick={() => setAuthMsg(null)}
            className="text-xs opacity-60 hover:opacity-100"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* ── Compact Header ────────────────────────────────────── */}
      <CompactHeader />

      {/* ── CPR Scanner ───────────────────────────────────────── */}
      <CPRScannerSection />

      {/* ── Engine + Positions + Orders ────────────────────────── */}
      <EngineControlPanel />

      {/* ── Trade Journal ─────────────────────────────────────── */}
      <TradeJournalPanel />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   COMPACT HEADER
   Single bar: title + auth | Daily P&L | Loss Budget | Win Rate |
   Profit Factor | Positions | Risk | Kill Switch
   ═══════════════════════════════════════════════════════════════════════════ */

function CompactHeader() {
  const { data: risk } = useRiskStatus();
  const { data: positions } = usePositions();
  const { data: strats } = useStrategies();
  const { data: perf } = usePerformance();
  const [session, setSession] = useState<{
    authenticated: boolean;
  } | null>(null);

  useEffect(() => {
    auth.getSession().then(setSession).catch(() => setSession(null));
  }, []);

  const openPositionCount = positions?.net?.length ?? 0;
  const runningStrategies =
    strats?.filter((s) => s.state === "running").length ?? 0;
  const isKillActive = risk?.kill_switch_active ?? false;

  const handleKillSwitch = async () => {
    try {
      if (isKillActive) {
        await config.deactivateKillSwitch();
      } else {
        await config.activateKillSwitch();
      }
    } catch {
      // SWR will refresh
    }
  };

  const lossPercent =
    risk && risk.daily_loss_limit > 0
      ? (risk.daily_loss / risk.daily_loss_limit) * 100
      : 0;

  return (
    <div className="space-y-3">
      {/* Title row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">
            CPR Trading Desk
          </h2>
          <p className="text-[var(--muted)] text-sm mt-0.5">
            Intraday narrow CPR breakout — scan, pick, trade
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Auth status */}
          <div
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs",
              session?.authenticated
                ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-400"
                : "border-red-500/30 bg-red-500/5 text-red-400"
            )}
          >
            <div
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                session?.authenticated
                  ? "bg-emerald-400 animate-pulse"
                  : "bg-red-400"
              )}
            />
            {session?.authenticated ? "Zerodha Connected" : "Not Connected"}
          </div>
          {/* Kill Switch */}
          <button
            onClick={handleKillSwitch}
            className={cn(
              "text-xs font-bold px-3 py-1.5 rounded-lg border transition-all",
              isKillActive
                ? "bg-red-500/20 text-red-400 border-red-500/40 hover:bg-red-500/30"
                : "bg-white/5 text-[var(--muted)] border-[var(--card-border)] hover:bg-white/10 hover:text-white"
            )}
          >
            {isKillActive ? "KILL ACTIVE" : "Kill Switch"}
          </button>
        </div>
      </div>

      {/* Metrics strip — single horizontal row */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Daily P&L */}
        <MetricChip
          label="Daily P&L"
          value={risk ? formatPnl(risk.daily_pnl) : "--"}
          valueClass={risk ? (risk.daily_pnl >= 0 ? "text-emerald-400" : "text-red-400") : ""}
        />

        {/* Loss Budget */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--card)] border border-[var(--card-border)]">
          <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Loss Budget</span>
          <div className="flex items-center gap-1.5">
            <div className="w-16 h-1.5 rounded-full bg-white/5 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  lossPercent > 80 ? "bg-red-500" : lossPercent > 50 ? "bg-amber-500" : "bg-emerald-500"
                )}
                style={{ width: `${Math.min(lossPercent, 100)}%` }}
              />
            </div>
            <span
              className="text-xs font-bold"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              {risk ? formatCurrency(risk.daily_loss_remaining) : "--"}
            </span>
          </div>
        </div>

        {/* Positions */}
        <MetricChip
          label="Positions"
          value={`${openPositionCount}`}
        />

        {/* Strategies */}
        <MetricChip
          label="Strategies"
          value={`${runningStrategies}`}
        />

        {/* Win Rate */}
        <MetricChip
          label="Win Rate"
          value={perf?.win_rate != null ? `${perf.win_rate.toFixed(1)}%` : "--"}
        />

        {/* Profit Factor */}
        <MetricChip
          label="PF"
          value={perf?.profit_factor != null ? perf.profit_factor.toFixed(2) : "--"}
          valueClass={
            perf?.profit_factor != null
              ? perf.profit_factor >= 1.5 ? "text-emerald-400" : perf.profit_factor >= 1.0 ? "text-amber-400" : "text-red-400"
              : ""
          }
        />

        {/* Order Rate (risk) */}
        {risk && (
          <MetricChip
            label="Orders/min"
            value={`${risk.orders_last_minute}/${risk.order_rate_limit}`}
          />
        )}
      </div>
    </div>
  );
}

/* ── Metric Chip (tiny inline metric) ─────────────────────────────────── */

function MetricChip({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--card)] border border-[var(--card-border)]">
      <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">{label}</span>
      <span
        className={cn("text-xs font-bold", valueClass)}
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {value}
      </span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CPR SCANNER
   Compact scanner with index checklist, results grouped by index,
   and a "Today's Top Picks" highlight section.
   ═══════════════════════════════════════════════════════════════════════════ */

function CPRScannerSection() {
  const [scanDate, setScanDate] = useState(
    () => new Date().toISOString().split("T")[0]
  );
  const [threshold, setThreshold] = useState(0.5);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<CPRScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showScanner, setShowScanner] = useState(true);

  const [availableIndices, setAvailableIndices] = useState<CPRIndexInfo[]>([]);
  const [selectedIndices, setSelectedIndices] = useState<Set<string>>(
    new Set()
  );
  const [indicesLoading, setIndicesLoading] = useState(true);

  useEffect(() => {
    backtest
      .cprIndices()
      .then((data) => {
        setAvailableIndices(data.indices);
        const withStocks = data.indices
          .filter((i) => i.constituent_count > 0)
          .map((i) => i.name);
        setSelectedIndices(new Set(withStocks));
      })
      .catch(() => {
        const fallback = [
          "NIFTY 50",
          "NIFTY BANK",
          "NIFTY IT",
          "NIFTY FIN SERVICE",
          "NIFTY PHARMA",
          "NIFTY AUTO",
          "NIFTY FMCG",
          "NIFTY ENERGY",
          "NIFTY INFRA",
          "NIFTY PSU BANK",
        ];
        setSelectedIndices(new Set(fallback));
      })
      .finally(() => setIndicesLoading(false));
  }, []);

  const toggleIndex = useCallback((name: string) => {
    setSelectedIndices((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIndices(
      new Set(availableIndices.filter((i) => i.constituent_count > 0).map((i) => i.name))
    );
  }, [availableIndices]);

  const selectNone = useCallback(() => {
    setSelectedIndices(new Set());
  }, []);

  const handleScan = async () => {
    if (selectedIndices.size === 0) {
      setError("Select at least one index");
      return;
    }
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const params: CPRScanParams = {
        scan_date: scanDate,
        indices: Array.from(selectedIndices),
        narrow_threshold: threshold,
      };
      const r = await backtest.cprScan(params);
      setResult(r);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "CPR scan failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="card !p-0 overflow-hidden">
        <button
          className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/[0.02] transition-colors"
          onClick={() => setShowScanner(!showScanner)}
        >
          <div className="flex items-center gap-3">
            <span
              className="text-[var(--muted)] text-xs transition-transform duration-200"
              style={{
                transform: showScanner ? "rotate(90deg)" : "rotate(0deg)",
              }}
            >
              &gt;
            </span>
            <h3 className="text-lg font-semibold tracking-tight">
              CPR Scanner
            </h3>
            {result && (
              <span className="text-xs text-[var(--muted)]">
                {result.summary.narrow_count} narrow /{" "}
                {result.summary.total_stocks_scanned} scanned
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {result && result.summary.narrow_count > 0 && (
              <span className="badge-success">
                {result.summary.narrow_count} picks
              </span>
            )}
          </div>
        </button>

        {showScanner && (
          <div className="px-6 pb-6 border-t border-[var(--card-border)]">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 pt-4">
              <div>
                <label className="block text-[10px] text-[var(--muted)] mb-1 uppercase tracking-wider">
                  Scan Date
                </label>
                <input
                  type="date"
                  className="input w-full"
                  value={scanDate}
                  onChange={(e) => setScanDate(e.target.value)}
                />
              </div>
              <div>
                <label className="block text-[10px] text-[var(--muted)] mb-1 uppercase tracking-wider">
                  Narrow Threshold %
                </label>
                <input
                  type="number"
                  className="input w-full"
                  value={threshold}
                  onChange={(e) => setThreshold(Number(e.target.value))}
                  min={0.05}
                  max={5}
                  step={0.05}
                />
              </div>
              <div className="flex items-end md:col-span-2">
                <button
                  className="btn-primary px-6 py-2"
                  onClick={handleScan}
                  disabled={running || selectedIndices.size === 0}
                >
                  {running ? (
                    <span className="flex items-center gap-2">
                      <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Scanning...
                    </span>
                  ) : (
                    `Scan ${selectedIndices.size} Indices`
                  )}
                </button>
              </div>
            </div>

            <div className="mt-4 pt-4 border-t border-[var(--card-border)]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
                  Indices
                </span>
                <div className="flex gap-2">
                  <button
                    className="text-[10px] text-blue-400 hover:text-blue-300"
                    onClick={selectAll}
                  >
                    All
                  </button>
                  <span className="text-[var(--card-border)]">|</span>
                  <button
                    className="text-[10px] text-blue-400 hover:text-blue-300"
                    onClick={selectNone}
                  >
                    None
                  </button>
                </div>
              </div>
              {indicesLoading ? (
                <p className="text-xs text-[var(--muted)]">Loading...</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {availableIndices.map((idx) => {
                    const checked = selectedIndices.has(idx.name);
                    const hasStocks = idx.constituent_count > 0;
                    return (
                      <button
                        key={idx.name}
                        disabled={!hasStocks}
                        onClick={() => toggleIndex(idx.name)}
                        className={cn(
                          "px-2.5 py-1 rounded-md text-[11px] border transition-all select-none",
                          checked
                            ? "border-brand-500/50 bg-brand-500/10 text-white"
                            : hasStocks
                              ? "border-[var(--card-border)] text-[var(--muted)] hover:border-white/20"
                              : "border-[var(--card-border)] text-[var(--muted)]/40 opacity-40 cursor-not-allowed"
                        )}
                      >
                        {idx.name.replace("NIFTY ", "")}
                        <span className="ml-1 opacity-50">
                          {idx.constituent_count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {error && <p className="text-sm text-red-400 mt-3">{error}</p>}
          </div>
        )}
      </div>

      {result && <ScanResultsInline result={result} />}
    </div>
  );
}

/* ── Inline Scan Results ──────────────────────────────────────────────── */

function ScanResultsInline({ result }: { result: CPRScanResult }) {
  const stocks = result.stocks;
  const sources = new Set(stocks.map((s) => s.data_source));
  const isMock = sources.has("mock_synthetic");
  const [loadingEngine, setLoadingEngine] = useState(false);
  const [loadResult, setLoadResult] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const indexNarrowCounts = new Map<string, number>();
  for (const stock of stocks) {
    if (stock.cpr.is_narrow) {
      for (const idx of stock.indices) {
        indexNarrowCounts.set(idx, (indexNarrowCounts.get(idx) ?? 0) + 1);
      }
    }
  }
  const bestIndex = Array.from(indexNarrowCounts.entries()).sort(
    (a, b) => b[1] - a[1]
  )[0]?.[0];

  const topPicks = stocks.filter((s) => s.cpr.is_narrow).slice(0, 5);

  const handleLoadToEngine = async () => {
    if (topPicks.length === 0) return;
    setLoadingEngine(true);
    setLoadResult(null);
    try {
      const picks = topPicks.map((s) => {
        let direction = "WAIT";
        if (s.today_open > s.cpr.tc) direction = "LONG";
        else if (s.today_open < s.cpr.bc) direction = "SHORT";
        return {
          trading_symbol: s.symbol,
          instrument_token: s.instrument_token,
          exchange: "NSE",
          direction,
          today_open: s.today_open,
          prev_close: s.prev_day.close,
          cpr: {
            pivot: s.cpr.pivot,
            tc: s.cpr.tc,
            bc: s.cpr.bc,
            width: s.cpr.width,
            width_pct: s.cpr.width_pct,
          },
        };
      });
      const res = await engine.loadPicks(picks);
      setLoadResult({
        type: "success",
        text: `Loaded ${res.picks_count} picks: ${res.symbols.join(", ")}`,
      });
    } catch (e: unknown) {
      setLoadResult({
        type: "error",
        text: e instanceof Error ? e.message : "Failed to load picks",
      });
    } finally {
      setLoadingEngine(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "text-xs px-2.5 py-1 rounded-md border",
            isMock
              ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
              : "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
          )}
        >
          {isMock ? "Mock Data" : "Zerodha Live"}
        </span>
        <span className="text-xs text-[var(--muted)]">
          {result.scan_date} | {result.summary.total_stocks_scanned} scanned |{" "}
          {result.summary.narrow_count} narrow | Threshold:{" "}
          {result.scan_params.narrow_threshold}%
        </span>
      </div>

      {topPicks.length > 0 ? (
        <div className="card !p-0 overflow-hidden border-emerald-500/20">
          <div className="px-6 py-3 bg-emerald-500/5 border-b border-emerald-500/15">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h3 className="text-sm font-semibold text-emerald-400">
                  Today&apos;s Top Picks
                </h3>
                {bestIndex && (
                  <span className="text-[10px] text-[var(--muted)]">
                    Best index: {bestIndex} ({indexNarrowCounts.get(bestIndex)}{" "}
                    narrow)
                  </span>
                )}
              </div>
              <div className="flex items-center gap-3">
                {loadResult && (
                  <span
                    className={cn(
                      "text-[10px]",
                      loadResult.type === "success"
                        ? "text-emerald-400"
                        : "text-red-400"
                    )}
                  >
                    {loadResult.text}
                  </span>
                )}
                <button
                  className="btn-primary px-3 py-1 text-[11px]"
                  onClick={handleLoadToEngine}
                  disabled={loadingEngine || topPicks.length === 0}
                >
                  {loadingEngine ? (
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Loading...
                    </span>
                  ) : (
                    `Load ${topPicks.length} to Engine`
                  )}
                </button>
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[var(--muted)] text-[10px] uppercase tracking-wider border-b border-[var(--card-border)]">
                  <th className="text-left py-2 pl-6 pr-2 w-10">#</th>
                  <th className="text-left py-2 px-2">Stock</th>
                  <th className="text-left py-2 px-2">Index</th>
                  <th className="text-right py-2 px-2">Prev Close</th>
                  <th className="text-right py-2 px-2">Open</th>
                  <th className="text-right py-2 px-2">Pivot</th>
                  <th className="text-right py-2 px-2">
                    <span className="text-blue-400">TC</span>
                  </th>
                  <th className="text-right py-2 px-2">
                    <span className="text-orange-400">BC</span>
                  </th>
                  <th className="text-right py-2 px-2">Width %</th>
                  <th className="text-center py-2 px-2 pr-6">Signal</th>
                </tr>
              </thead>
              <tbody>
                {topPicks.map((stock, idx) => (
                  <TopPickRow key={stock.instrument_token} stock={stock} rank={idx + 1} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : stocks.length > 0 ? (
        <div className="card !p-4 text-center">
          <p className="text-sm text-[var(--muted)]">
            No narrow CPR stocks found. All {stocks.length} stocks have wide
            CPR today — no strong breakout candidates.
          </p>
        </div>
      ) : null}

      {stocks.length > 0 && (
        <FullResultsPanel stocks={stocks} indices={result.scan_params.indices_selected} errors={result.errors} />
      )}
    </div>
  );
}

/* ── Top Pick Row ─────────────────────────────────────────────────────── */

function TopPickRow({ stock, rank }: { stock: CPRStockEntry; rank: number }) {
  const { cpr, prev_day } = stock;

  let signal: "LONG" | "SHORT" | "WAIT" = "WAIT";
  let signalColor = "text-[var(--muted)]";
  let signalBg = "bg-white/5";

  if (stock.today_open > cpr.tc) {
    signal = "LONG";
    signalColor = "text-emerald-400";
    signalBg = "bg-emerald-500/10";
  } else if (stock.today_open < cpr.bc) {
    signal = "SHORT";
    signalColor = "text-red-400";
    signalBg = "bg-red-500/10";
  }

  return (
    <tr className="border-t border-[var(--card-border)] hover:bg-emerald-500/[0.03] transition-colors">
      <td
        className="py-3 pl-6 pr-2 font-medium text-[var(--muted)]"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {rank}
      </td>
      <td className="py-3 px-2">
        <span className="font-medium">{stock.symbol}</span>
        <span className="text-xs text-[var(--muted)] ml-2 hidden md:inline">
          {stock.name}
        </span>
      </td>
      <td className="py-3 px-2 text-xs text-[var(--muted)]">
        {stock.indices[0]?.replace("NIFTY ", "") ?? "-"}
        {stock.indices.length > 1 && (
          <span className="opacity-50"> +{stock.indices.length - 1}</span>
        )}
      </td>
      <td
        className="py-3 px-2 text-right text-[var(--muted)]"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(prev_day.close)}
      </td>
      <td
        className="py-3 px-2 text-right"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(stock.today_open)}
      </td>
      <td
        className="py-3 px-2 text-right font-medium"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(cpr.pivot)}
      </td>
      <td
        className="py-3 px-2 text-right text-blue-400"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(cpr.tc)}
      </td>
      <td
        className="py-3 px-2 text-right text-orange-400"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(cpr.bc)}
      </td>
      <td
        className="py-3 px-2 text-right font-semibold text-emerald-400"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {cpr.width_pct.toFixed(3)}%
      </td>
      <td className="py-3 px-2 pr-6 text-center">
        <span
          className={cn(
            "inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
            signalBg,
            signalColor
          )}
        >
          {signal}
        </span>
      </td>
    </tr>
  );
}

/* ── Full Results (collapsible grouped by index) ──────────────────────── */

function FullResultsPanel({
  stocks,
  indices,
  errors,
}: {
  stocks: CPRStockEntry[];
  indices: string[];
  errors: CPRScanResult["errors"];
}) {
  const [expanded, setExpanded] = useState(false);

  const groupMap = new Map<string, CPRStockEntry[]>();
  for (const indexName of indices) {
    const matching = stocks
      .filter((s) => s.indices.includes(indexName))
      .sort((a, b) => a.cpr.width_pct - b.cpr.width_pct);
    if (matching.length > 0) {
      groupMap.set(indexName, matching);
    }
  }
  const sortedGroups = Array.from(groupMap.entries()).sort(
    ([, a], [, b]) => a[0].cpr.width_pct - b[0].cpr.width_pct
  );

  return (
    <div className="card !p-0 overflow-hidden">
      <button
        className="w-full px-6 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-[var(--muted)] text-xs transition-transform duration-200"
            style={{
              transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            }}
          >
            &gt;
          </span>
          <span className="text-sm font-medium">
            All Results by Index
          </span>
          <span className="text-xs text-[var(--muted)]">
            {sortedGroups.length} indices · {stocks.length} stocks
          </span>
        </div>
        {errors && errors.length > 0 && (
          <span className="text-[10px] text-red-400">
            {errors.length} errors
          </span>
        )}
      </button>

      {expanded && (
        <div className="border-t border-[var(--card-border)]">
          {errors && errors.length > 0 && (
            <div className="px-6 py-3 bg-red-500/5 border-b border-red-500/10">
              <p className="text-xs text-red-400 font-medium mb-1">
                Scan Errors:
              </p>
              <div className="space-y-0.5">
                {errors.slice(0, 10).map((err, i) => (
                  <p key={i} className="text-[10px] text-red-400/70">
                    {err.symbol}: {err.error}
                  </p>
                ))}
                {errors.length > 10 && (
                  <p className="text-[10px] text-red-400/50">
                    ...and {errors.length - 10} more
                  </p>
                )}
              </div>
            </div>
          )}

          {sortedGroups.map(([indexName, indexStocks]) => (
            <IndexGroupCompact
              key={indexName}
              indexName={indexName}
              stocks={indexStocks}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Compact Index Group ──────────────────────────────────────────────── */

function IndexGroupCompact({
  indexName,
  stocks,
}: {
  indexName: string;
  stocks: CPRStockEntry[];
}) {
  const [showAll, setShowAll] = useState(false);
  const narrowCount = stocks.filter((s) => s.cpr.is_narrow).length;
  const visible = showAll ? stocks : stocks.slice(0, 5);
  const narrowestPct = stocks[0]?.cpr.width_pct ?? 999;

  return (
    <div className="border-b border-[var(--card-border)] last:border-b-0">
      <div className="px-6 py-2.5 flex items-center justify-between bg-white/[0.015]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold">{indexName}</span>
          <span className="text-[10px] text-[var(--muted)]">
            {stocks.length} stocks
          </span>
          {narrowCount > 0 && (
            <span className="text-[10px] text-emerald-400 font-medium">
              {narrowCount} narrow
            </span>
          )}
        </div>
        <span
          className="text-[10px] text-[var(--muted)]"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          best: {narrowestPct.toFixed(3)}%
        </span>
      </div>

      <div className="px-6 py-2 space-y-1">
        {visible.map((stock) => (
          <CompactStockRow key={stock.instrument_token} stock={stock} />
        ))}
        {stocks.length > 5 && (
          <button
            className="text-[10px] text-blue-400 hover:text-blue-300 py-1"
            onClick={() => setShowAll(!showAll)}
          >
            {showAll
              ? "Show less"
              : `+${stocks.length - 5} more`}
          </button>
        )}
      </div>
    </div>
  );
}

function CompactStockRow({ stock }: { stock: CPRStockEntry }) {
  const { cpr } = stock;
  return (
    <div className="flex items-center justify-between text-xs py-0.5">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full flex-shrink-0",
            cpr.is_narrow ? "bg-emerald-400" : "bg-white/10"
          )}
        />
        <span className="font-medium truncate">{stock.symbol}</span>
      </div>
      <div
        className="flex items-center gap-4 flex-shrink-0 text-[var(--muted)]"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        <span>P:{formatNumber(cpr.pivot)}</span>
        <span className="text-blue-400">TC:{formatNumber(cpr.tc)}</span>
        <span className="text-orange-400">BC:{formatNumber(cpr.bc)}</span>
        <span
          className={cn(
            "font-medium w-16 text-right",
            cpr.is_narrow ? "text-emerald-400" : "text-[var(--muted)]"
          )}
        >
          {cpr.width_pct.toFixed(3)}%
        </span>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   ENGINE CONTROL PANEL
   Engine state, start/stop/pause, strategies, events, decision logs,
   PLUS embedded positions and recent orders (consolidated view).
   ═══════════════════════════════════════════════════════════════════════════ */

function EngineControlPanel() {
  const { data: swrStatus, mutate: mutateStatus } = useEngineStatus();
  const { data: swrEvents } = useEngineEvents(30);
  const { data: positionsData } = usePositions();
  const { data: ordersData, isLoading: ordersLoading } = useOrders();

  // Track live tick prices
  const [livePrices, setLivePrices] = useState<Record<number, number>>({});
  const handleTick = useCallback(
    (tick: { instrument_token: number; last_price: number }) => {
      setLivePrices((prev) => {
        if (prev[tick.instrument_token] === tick.last_price) return prev;
        return { ...prev, [tick.instrument_token]: tick.last_price };
      });
    },
    [],
  );

  const {
    connected: wsConnected,
    status: wsStatus,
    events: wsEvents,
    subscribeTokens,
  } = useEngineStream({ onTick: handleTick });
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);

  const status = wsConnected && wsStatus ? wsStatus : swrStatus;
  const events = wsConnected && wsEvents.length > 0 ? wsEvents : (swrEvents ?? swrStatus?.recent_events ?? []);

  const state = status?.state ?? "idle";
  const isRunning = state === "running";
  const isPaused = state === "paused";
  const hasPicks = (status?.picks_count ?? 0) > 0;

  // Positions and orders
  const positions = positionsData?.net ?? [];
  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);
  const recentOrders = ordersData?.slice(-8).reverse() ?? [];

  // Subscribe to tick data
  const subscribedRef = useRef<string>("");
  useEffect(() => {
    if (!wsConnected || !status?.strategies) return;
    const tokens = Object.keys(status.strategies).map(Number).filter(Boolean);
    const key = tokens.sort().join(",");
    if (key && key !== subscribedRef.current) {
      subscribeTokens(tokens);
      subscribedRef.current = key;
    }
  }, [wsConnected, status?.strategies, subscribeTokens]);

  const handleAction = async (action: string) => {
    setActionLoading(action);
    setActionError(null);
    try {
      switch (action) {
        case "start":
          await engine.start();
          break;
        case "stop":
          await engine.stop();
          break;
        case "pause":
          await engine.pause();
          break;
        case "resume":
          await engine.resume();
          break;
      }
      await mutateStatus();
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : `${action} failed`);
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="card !p-0 overflow-hidden">
      {/* Header */}
      <button
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-white/[0.02] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-[var(--muted)] text-xs transition-transform duration-200"
            style={{
              transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
            }}
          >
            &gt;
          </span>
          <h3 className="text-lg font-semibold tracking-tight">
            Trading Engine
          </h3>
          <EngineStateBadge state={state} />
          {status?.is_paper && (
            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
              Paper
            </span>
          )}
          {hasPicks && (
            <span className="text-xs text-[var(--muted)]">
              {status!.picks_count} picks loaded
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {/* Connection indicators */}
          <span
            className={cn(
              "flex items-center gap-1.5 text-[10px]",
              wsConnected ? "text-emerald-400" : "text-[var(--muted)]"
            )}
          >
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                wsConnected ? "bg-emerald-400 animate-pulse" : "bg-[var(--muted)]/40"
              )}
            />
            {wsConnected ? "Live" : "Polling"}
          </span>
          {status?.ticker_connected && (
            <span className="flex items-center gap-1.5 text-[10px] text-emerald-400">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Ticker
            </span>
          )}
          {/* Positions count + P&L inline */}
          {positions.length > 0 && (
            <span className="flex items-center gap-1.5 text-xs">
              <span className="text-[var(--muted)]">{positions.length} pos</span>
              <span
                className={cn(
                  "font-bold",
                  totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
                )}
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                {formatPnl(totalPnl)}
              </span>
            </span>
          )}
          {status && status.metrics.session_pnl !== 0 && (
            <span
              className={cn(
                "text-sm font-bold",
                status.metrics.session_pnl >= 0 ? "text-emerald-400" : "text-red-400"
              )}
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              {formatPnl(status.metrics.session_pnl)}
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-[var(--card-border)]">
          {/* Controls bar */}
          <div className="px-6 py-4 flex items-center justify-between border-b border-[var(--card-border)] bg-white/[0.01]">
            <div className="flex items-center gap-2">
              {!isRunning && !isPaused && (
                <button
                  className="btn-primary px-4 py-1.5 text-xs"
                  onClick={(e) => { e.stopPropagation(); handleAction("start"); }}
                  disabled={!hasPicks || actionLoading !== null}
                >
                  {actionLoading === "start" ? (
                    <span className="flex items-center gap-1.5">
                      <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      Starting...
                    </span>
                  ) : (
                    "Start Engine"
                  )}
                </button>
              )}
              {isRunning && (
                <button
                  className="btn-outline px-4 py-1.5 text-xs"
                  onClick={(e) => { e.stopPropagation(); handleAction("pause"); }}
                  disabled={actionLoading !== null}
                >
                  {actionLoading === "pause" ? "Pausing..." : "Pause"}
                </button>
              )}
              {isPaused && (
                <button
                  className="btn-primary px-4 py-1.5 text-xs"
                  onClick={(e) => { e.stopPropagation(); handleAction("resume"); }}
                  disabled={actionLoading !== null}
                >
                  {actionLoading === "resume" ? "Resuming..." : "Resume"}
                </button>
              )}
              {(isRunning || isPaused) && (
                <button
                  className="px-4 py-1.5 text-xs rounded-md border border-red-500/30 bg-red-500/5 text-red-400 hover:bg-red-500/10 transition-colors"
                  onClick={(e) => { e.stopPropagation(); handleAction("stop"); }}
                  disabled={actionLoading !== null}
                >
                  {actionLoading === "stop" ? "Stopping..." : "Stop Engine"}
                </button>
              )}
              {!hasPicks && state === "idle" && (
                <span className="text-xs text-[var(--muted)]">
                  Run a CPR scan and load picks to start
                </span>
              )}
            </div>
            {status && (
              <div
                className="flex items-center gap-5 text-xs text-[var(--muted)]"
                style={{ fontFamily: "'JetBrains Mono', monospace" }}
              >
                <span>Signals: {status.metrics.total_signals}</span>
                <span>Orders: {status.metrics.total_orders}</span>
                <span>Fills: {status.metrics.total_fills}</span>
              </div>
            )}
          </div>

          {actionError && (
            <div className="px-6 py-2 bg-red-500/5 border-b border-red-500/10">
              <p className="text-xs text-red-400">{actionError}</p>
            </div>
          )}

          {/* Strategies + Events side by side */}
          {hasPicks && (
            <div className="grid grid-cols-1 lg:grid-cols-5 divide-y lg:divide-y-0 lg:divide-x divide-[var(--card-border)]">
              <div className="lg:col-span-3 p-4">
                <EngineStrategiesTable strategies={status?.strategies ?? {}} livePrices={livePrices} />
              </div>
              <div className="lg:col-span-2 p-4">
                <EngineEventFeed events={events} />
              </div>
            </div>
          )}

          {/* Decision Logs */}
          {hasPicks && (
            <div className="border-t border-[var(--card-border)]">
              <div className="p-4">
                <DecisionLogsPanel />
              </div>
            </div>
          )}

          {/* Positions + Orders — embedded in engine panel */}
          {(positions.length > 0 || recentOrders.length > 0) && (
            <div className="border-t border-[var(--card-border)]">
              <div className="grid grid-cols-1 lg:grid-cols-5 divide-y lg:divide-y-0 lg:divide-x divide-[var(--card-border)]">
                {/* Positions */}
                <div className="lg:col-span-3 p-4">
                  <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider mb-3">
                    Open Positions
                    {positions.length > 0 && (
                      <span
                        className={cn(
                          "ml-2 text-xs font-bold",
                          totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
                        )}
                        style={{ fontFamily: "'JetBrains Mono', monospace" }}
                      >
                        Total: {formatPnl(totalPnl)}
                      </span>
                    )}
                  </p>
                  {positions.length === 0 ? (
                    <p className="text-xs text-[var(--muted)] text-center py-4">
                      No open positions
                    </p>
                  ) : (
                    <div className="space-y-1.5">
                      {positions.map((p) => (
                        <div
                          key={p.trading_symbol}
                          className="flex items-center justify-between py-2.5 px-3 rounded-lg bg-white/[0.02] border border-[var(--card-border)]"
                        >
                          <div className="flex items-center gap-2.5">
                            <span
                              className={cn(
                                "text-[10px] font-bold px-1.5 py-0.5 rounded",
                                p.quantity > 0
                                  ? "bg-emerald-500/10 text-emerald-400"
                                  : "bg-red-500/10 text-red-400"
                              )}
                            >
                              {p.quantity > 0 ? "LONG" : "SHORT"}
                            </span>
                            <span className="font-medium text-sm">{p.trading_symbol}</span>
                            <span className="text-[10px] text-[var(--muted)]">{p.exchange}</span>
                          </div>
                          <div className="flex items-center gap-4">
                            <span
                              className="text-[10px] text-[var(--muted)]"
                              style={{ fontFamily: "'JetBrains Mono', monospace" }}
                            >
                              {Math.abs(p.quantity)} @ {formatNumber(p.average_price)} | LTP {formatNumber(p.last_price)}
                            </span>
                            <span
                              className={cn(
                                "text-sm font-bold min-w-[70px] text-right",
                                p.pnl >= 0 ? "pnl-positive" : "pnl-negative"
                              )}
                              style={{ fontFamily: "'JetBrains Mono', monospace" }}
                            >
                              {formatPnl(p.pnl)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Recent Orders */}
                <div className="lg:col-span-2 p-4">
                  <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider mb-3">
                    Recent Orders
                  </p>
                  {ordersLoading ? (
                    <p className="text-xs text-[var(--muted)] text-center py-4">Loading...</p>
                  ) : recentOrders.length === 0 ? (
                    <p className="text-xs text-[var(--muted)] text-center py-4">
                      No orders today
                    </p>
                  ) : (
                    <div className="space-y-1.5">
                      {recentOrders.map((o) => (
                        <div
                          key={o.order_id}
                          className="flex items-center justify-between py-2 px-3 rounded-lg bg-white/[0.015]"
                        >
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                "text-[10px] font-bold px-1.5 py-0.5 rounded",
                                o.transaction_type === "BUY"
                                  ? "bg-emerald-500/10 text-emerald-400"
                                  : "bg-red-500/10 text-red-400"
                              )}
                            >
                              {o.transaction_type}
                            </span>
                            <span className="text-xs font-medium">{o.trading_symbol}</span>
                            <span className="text-[10px] text-[var(--muted)]">
                              x{o.quantity}
                            </span>
                          </div>
                          <OrderStatusBadge status={o.status} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Engine State Badge ──────────────────────────────────────────────── */

function EngineStateBadge({ state }: { state: string }) {
  const stateConfig: Record<string, { label: string; className: string }> = {
    idle: {
      label: "IDLE",
      className: "bg-white/5 text-[var(--muted)] border-[var(--card-border)]",
    },
    loading: {
      label: "LOADING",
      className: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    },
    running: {
      label: "RUNNING",
      className: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    },
    paused: {
      label: "PAUSED",
      className: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    },
    stopping: {
      label: "STOPPING",
      className: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    },
    stopped: {
      label: "STOPPED",
      className: "bg-white/5 text-[var(--muted)] border-[var(--card-border)]",
    },
    error: {
      label: "ERROR",
      className: "bg-red-500/10 text-red-400 border-red-500/20",
    },
  };

  const cfg = stateConfig[state] ?? stateConfig.idle;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wider border",
        cfg.className
      )}
    >
      {state === "running" && (
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
      )}
      {cfg.label}
    </span>
  );
}

/* ── Engine Strategies Table ─────────────────────────────────────────── */

function EngineStrategiesTable({
  strategies,
  livePrices,
}: {
  strategies: Record<string, EngineStrategyDetail>;
  livePrices: Record<number, number>;
}) {
  const entries = Object.entries(strategies);

  if (entries.length === 0) {
    return (
      <p className="text-xs text-[var(--muted)] text-center py-4">
        No strategies loaded
      </p>
    );
  }

  return (
    <div>
      <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider mb-3">
        Strategy Instances
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[var(--muted)] text-[10px] uppercase tracking-wider border-b border-[var(--card-border)]">
              <th className="text-left py-2 pr-2">Stock</th>
              <th className="text-center py-2 px-2">Dir</th>
              <th className="text-center py-2 px-2">State</th>
              <th className="text-right py-2 px-2">CPR %</th>
              <th className="text-center py-2 px-2">Position</th>
              <th className="text-right py-2 px-2">LTP</th>
              <th className="text-right py-2 px-2">Entry</th>
              <th className="text-right py-2 px-2">SL</th>
              <th className="text-right py-2 px-2">Target</th>
              <th className="text-right py-2 pl-2">P&L</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([token, s]) => {
              const ltp = livePrices[Number(token)];
              let unrealizedPnl: number | null = null;
              if (ltp && s.position && s.entry_price > 0) {
                unrealizedPnl = s.position === "LONG"
                  ? ltp - s.entry_price
                  : s.entry_price - ltp;
              }
              return (
                <tr
                  key={token}
                  className="border-t border-[var(--card-border)] hover:bg-white/[0.02] transition-colors"
                >
                  <td className="py-2 pr-2 font-medium">{s.symbol}</td>
                  <td className="py-2 px-2 text-center">
                    <span
                      className={cn(
                        "inline-block px-1.5 py-0.5 rounded text-[10px] font-bold",
                        s.direction === "LONG"
                          ? "bg-emerald-500/10 text-emerald-400"
                          : s.direction === "SHORT"
                            ? "bg-red-500/10 text-red-400"
                            : "bg-white/5 text-[var(--muted)]"
                      )}
                    >
                      {s.direction}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-center">
                    <span
                      className={cn(
                        "text-[10px]",
                        s.state === "running"
                          ? "text-emerald-400"
                          : s.state === "paused"
                            ? "text-amber-400"
                            : "text-[var(--muted)]"
                      )}
                    >
                      {s.state}
                    </span>
                  </td>
                  <td
                    className="py-2 px-2 text-right text-emerald-400"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {s.cpr ? s.cpr.width_pct.toFixed(3) + "%" : "-"}
                  </td>
                  <td className="py-2 px-2 text-center">
                    {s.position ? (
                      <span
                        className={cn(
                          "text-[10px] font-bold",
                          s.position === "LONG"
                            ? "text-emerald-400"
                            : "text-red-400"
                        )}
                      >
                        {s.position}
                      </span>
                    ) : s.traded_today ? (
                      <span className="text-[10px] text-[var(--muted)]">done</span>
                    ) : (
                      <span className="text-[10px] text-[var(--muted)]">--</span>
                    )}
                  </td>
                  <td
                    className={cn(
                      "py-2 px-2 text-right",
                      ltp ? "text-white" : "text-[var(--muted)]"
                    )}
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {ltp ? formatNumber(ltp) : "--"}
                  </td>
                  <td
                    className="py-2 px-2 text-right"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {s.entry_price > 0 ? formatNumber(s.entry_price) : "--"}
                  </td>
                  <td
                    className="py-2 px-2 text-right text-red-400/70"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {s.stop_loss > 0 ? formatNumber(s.stop_loss) : "--"}
                  </td>
                  <td
                    className="py-2 px-2 text-right text-emerald-400/70"
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {s.target > 0 ? formatNumber(s.target) : "--"}
                  </td>
                  <td
                    className={cn(
                      "py-2 pl-2 text-right font-bold",
                      unrealizedPnl !== null
                        ? unrealizedPnl >= 0 ? "text-emerald-400" : "text-red-400"
                        : s.metrics.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                    )}
                    style={{ fontFamily: "'JetBrains Mono', monospace" }}
                  >
                    {unrealizedPnl !== null
                      ? formatPnl(unrealizedPnl)
                      : s.metrics.total_pnl !== 0
                        ? formatPnl(s.metrics.total_pnl)
                        : "--"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Engine Event Feed ───────────────────────────────────────────────── */

function EngineEventFeed({ events }: { events: EngineEvent[] }) {
  const displayed = [...events].reverse().slice(0, 20);

  return (
    <div>
      <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider mb-3">
        Event Feed
      </p>
      {displayed.length === 0 ? (
        <p className="text-xs text-[var(--muted)] text-center py-4">
          No events yet
        </p>
      ) : (
        <div className="space-y-1 max-h-[280px] overflow-y-auto">
          {displayed.map((e, i) => (
            <div
              key={`${e.timestamp}-${i}`}
              className="flex items-start gap-2 py-1.5 px-2 rounded hover:bg-white/[0.02]"
            >
              <EventTypeIcon type={e.type} />
              <div className="min-w-0 flex-1">
                <p className="text-xs leading-tight">{e.message}</p>
                <p
                  className="text-[10px] text-[var(--muted)] mt-0.5"
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  {formatEventTime(e.timestamp)}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EventTypeIcon({ type }: { type: string }) {
  const iconConfig: Record<string, { color: string; symbol: string }> = {
    signal: { color: "text-blue-400", symbol: "~" },
    order: { color: "text-amber-400", symbol: "$" },
    fill: { color: "text-emerald-400", symbol: "+" },
    exit: { color: "text-orange-400", symbol: "-" },
    error: { color: "text-red-400", symbol: "!" },
    scan: { color: "text-purple-400", symbol: "#" },
    info: { color: "text-[var(--muted)]", symbol: ">" },
    "log:strategy": { color: "text-cyan-400", symbol: "S" },
    "log:risk": { color: "text-amber-400", symbol: "R" },
    "log:order_manager": { color: "text-emerald-400", symbol: "O" },
    "log:engine": { color: "text-purple-400", symbol: "E" },
    "log:system": { color: "text-[var(--muted)]", symbol: "L" },
  };
  const c = iconConfig[type] ?? iconConfig.info;
  return (
    <span
      className={cn("text-[10px] font-bold w-3 flex-shrink-0 text-center mt-0.5", c.color)}
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      {c.symbol}
    </span>
  );
}

function formatEventTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

/* ── Decision Logs Panel ─────────────────────────────────────────────── */

function DecisionLogsPanel() {
  const [component, setComponent] = useState<string>("");
  const [level, setLevel] = useState<string>("");
  const { data, mutate: mutateLogs } = useDecisionLogs({
    component: component || undefined,
    level: level || undefined,
    limit: 100,
  });

  const entries = data?.entries ?? [];

  const levelColors: Record<string, string> = {
    debug: "text-[var(--muted)]",
    info: "text-blue-400",
    warn: "text-amber-400",
    error: "text-red-400",
  };

  const componentLabels: Record<string, string> = {
    strategy: "STR",
    risk: "RSK",
    order_manager: "ORD",
    engine: "ENG",
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider font-semibold">
          Decision Logs
          {data ? ` (${data.count}/${data.total_buffered})` : ""}
        </p>
        <div className="flex items-center gap-2">
          <select
            className="text-[10px] bg-[var(--background)] border border-[var(--card-border)] rounded px-1.5 py-0.5 text-[var(--muted)]"
            value={component}
            onChange={(e) => setComponent(e.target.value)}
          >
            <option value="">All Components</option>
            <option value="strategy">Strategy</option>
            <option value="risk">Risk</option>
            <option value="order_manager">Order Manager</option>
            <option value="engine">Engine</option>
          </select>
          <select
            className="text-[10px] bg-[var(--background)] border border-[var(--card-border)] rounded px-1.5 py-0.5 text-[var(--muted)]"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          >
            <option value="">All Levels</option>
            <option value="debug">Debug</option>
            <option value="info">Info</option>
            <option value="warn">Warn</option>
            <option value="error">Error</option>
          </select>
          <button
            className="text-[10px] text-[var(--muted)] hover:text-white border border-[var(--card-border)] rounded px-2 py-0.5 transition-colors"
            onClick={async () => {
              await engine.clearLogs();
              mutateLogs();
            }}
          >
            Clear
          </button>
        </div>
      </div>
      {entries.length === 0 ? (
        <p className="text-xs text-[var(--muted)] text-center py-6">
          No decision logs yet. Start the engine to see decisions.
        </p>
      ) : (
        <div className="space-y-0.5 max-h-[320px] overflow-y-auto font-mono text-[11px]">
          {[...entries].reverse().map((entry, i) => (
            <div
              key={`${entry.timestamp}-${i}`}
              className="flex items-start gap-2 py-1 px-2 rounded hover:bg-white/[0.02]"
            >
              <span className={cn(
                "flex-shrink-0 w-[26px] text-center text-[9px] font-bold uppercase rounded px-0.5",
                entry.level === "error" ? "bg-red-500/15 text-red-400" :
                entry.level === "warn" ? "bg-amber-500/15 text-amber-400" :
                entry.level === "info" ? "bg-blue-500/10 text-blue-400" :
                "bg-white/5 text-[var(--muted)]"
              )}>
                {entry.level.slice(0, 3).toUpperCase()}
              </span>
              <span className="flex-shrink-0 w-[24px] text-[9px] font-bold text-[var(--muted)]">
                {componentLabels[entry.component] ?? entry.component.slice(0, 3).toUpperCase()}
              </span>
              <span className={cn("flex-1 min-w-0 truncate", levelColors[entry.level] ?? "text-white")}>
                {entry.message}
              </span>
              <span className="flex-shrink-0 text-[9px] text-[var(--muted)]">
                {formatEventTime(entry.timestamp)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Order Status Badge ──────────────────────────────────────────────── */

function OrderStatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    COMPLETE: "badge-success",
    REJECTED: "badge-danger",
    CANCELLED: "badge-warning",
    PENDING: "badge-info",
    OPEN: "badge-info",
  };

  return (
    <span className={cn("text-[10px]", styles[status] || "badge-info")}>
      {status}
    </span>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   TRADE JOURNAL TABLE
   Recent trades with direction, P&L, exit reason, and status
   ═══════════════════════════════════════════════════════════════════════════ */

function TradeJournalPanel() {
  const [showClosedOnly, setShowClosedOnly] = useState(false);
  const [symbolFilter, setSymbolFilter] = useState("");

  const { data, isLoading } = useJournalTrades({
    closed_only: showClosedOnly,
    symbol: symbolFilter || undefined,
    limit: 20,
  });

  const trades = data?.trades ?? [];
  const totalCount = data?.total ?? 0;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold">Trade Journal</h3>
          <span className="text-[10px] text-[var(--muted)]">
            {totalCount} trade{totalCount !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Filter symbol..."
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value.toUpperCase())}
            className="h-7 px-2.5 text-xs rounded-md border border-[var(--card-border)] bg-transparent focus:outline-none focus:border-[var(--accent)] w-32"
          />
          <button
            onClick={() => setShowClosedOnly(!showClosedOnly)}
            className={cn(
              "h-7 px-2.5 text-[10px] rounded-md border transition-colors",
              showClosedOnly
                ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10"
                : "border-[var(--card-border)] text-[var(--muted)] hover:text-[var(--foreground)]"
            )}
          >
            Closed Only
          </button>
        </div>
      </div>

      {isLoading && (
        <p className="text-[var(--muted)] text-sm text-center py-6">Loading trades...</p>
      )}

      {!isLoading && trades.length === 0 && (
        <p className="text-[var(--muted)] text-xs text-center py-8">
          No trades recorded yet. Start the engine to begin tracking.
        </p>
      )}

      {!isLoading && trades.length > 0 && (
        <div className="overflow-x-auto -mx-6 px-6">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] text-[var(--muted)] uppercase tracking-wider border-b border-[var(--card-border)]">
                <th className="text-left pb-2 pr-3">Symbol</th>
                <th className="text-left pb-2 pr-3">Dir</th>
                <th className="text-right pb-2 pr-3">Entry</th>
                <th className="text-right pb-2 pr-3">Exit</th>
                <th className="text-right pb-2 pr-3">Qty</th>
                <th className="text-right pb-2 pr-3">P&amp;L</th>
                <th className="text-right pb-2 pr-3">P&amp;L %</th>
                <th className="text-right pb-2 pr-3">R:R</th>
                <th className="text-left pb-2 pr-3">Exit Reason</th>
                <th className="text-right pb-2 pr-3">Duration</th>
                <th className="text-center pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <TradeRow key={t.trade_id} trade={t} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TradeRow({ trade }: { trade: JournalTrade }) {
  const isProfit = trade.pnl >= 0;
  const mono = { fontFamily: "'JetBrains Mono', monospace" } as const;

  return (
    <tr className="border-b border-[var(--card-border)]/50 hover:bg-white/[0.015] transition-colors">
      <td className="py-2.5 pr-3">
        <div className="flex items-center gap-1.5">
          <span className="font-medium">{trade.trading_symbol}</span>
          {trade.is_paper && (
            <span className="text-[9px] text-amber-400/70 bg-amber-500/10 px-1 rounded">
              PAPER
            </span>
          )}
        </div>
      </td>
      <td className="py-2.5 pr-3">
        <span
          className={cn(
            "text-[10px] font-bold px-1.5 py-0.5 rounded",
            trade.direction === "LONG"
              ? "bg-emerald-500/10 text-emerald-400"
              : "bg-red-500/10 text-red-400"
          )}
        >
          {trade.direction}
        </span>
      </td>
      <td className="py-2.5 pr-3 text-right" style={mono}>
        {formatNumber(trade.entry_price, 2)}
      </td>
      <td className="py-2.5 pr-3 text-right text-[var(--muted)]" style={mono}>
        {trade.exit_price ? formatNumber(trade.exit_price, 2) : "\u2014"}
      </td>
      <td className="py-2.5 pr-3 text-right" style={mono}>
        {trade.quantity}
      </td>
      <td
        className={cn(
          "py-2.5 pr-3 text-right font-medium",
          trade.is_open ? "text-[var(--muted)]" : isProfit ? "text-emerald-400" : "text-red-400"
        )}
        style={mono}
      >
        {trade.is_open ? "\u2014" : formatPnl(trade.pnl)}
      </td>
      <td
        className={cn(
          "py-2.5 pr-3 text-right",
          trade.is_open ? "text-[var(--muted)]" : isProfit ? "text-emerald-400" : "text-red-400"
        )}
        style={mono}
      >
        {trade.is_open ? "\u2014" : `${trade.pnl_pct >= 0 ? "+" : ""}${trade.pnl_pct.toFixed(2)}%`}
      </td>
      <td className="py-2.5 pr-3 text-right" style={mono}>
        {trade.risk_reward_actual != null ? trade.risk_reward_actual.toFixed(2) : "\u2014"}
      </td>
      <td className="py-2.5 pr-3 text-left">
        <ExitReasonBadge reason={trade.exit_reason} isOpen={trade.is_open} />
      </td>
      <td className="py-2.5 pr-3 text-right text-[var(--muted)]" style={mono}>
        {trade.duration_minutes != null
          ? `${trade.duration_minutes.toFixed(0)}m`
          : "\u2014"}
      </td>
      <td className="py-2.5 text-center">
        <span
          className={cn(
            "inline-block w-2 h-2 rounded-full",
            trade.is_open ? "bg-amber-400 animate-pulse" : isProfit ? "bg-emerald-400" : "bg-red-400"
          )}
          title={trade.is_open ? "Open" : isProfit ? "Winner" : "Loser"}
        />
      </td>
    </tr>
  );
}

function ExitReasonBadge({ reason, isOpen }: { reason: string; isOpen: boolean }) {
  if (isOpen || !reason) {
    return <span className="text-[10px] text-amber-400/70">ACTIVE</span>;
  }

  const styles: Record<string, string> = {
    target: "text-emerald-400 bg-emerald-500/10",
    stop_loss: "text-red-400 bg-red-500/10",
    trailing_sl: "text-amber-400 bg-amber-500/10",
    eod: "text-blue-400 bg-blue-500/10",
    engine_stop: "text-[var(--muted)] bg-white/5",
    manual: "text-purple-400 bg-purple-500/10",
  };

  const label = reason.replace(/_/g, " ").toUpperCase();
  const style = styles[reason] || "text-[var(--muted)] bg-white/5";

  return (
    <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded", style)}>
      {label}
    </span>
  );
}
