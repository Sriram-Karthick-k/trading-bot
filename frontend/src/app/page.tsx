"use client";

import { useEffect, useState, useCallback } from "react";
import {
  useOrders,
  usePositions,
  useRiskStatus,
  useStrategies,
  useEngineStatus,
  useEngineEvents,
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
import type { EngineEvent, EngineStrategyDetail } from "@/types";
import { formatCurrency, formatPnl, formatNumber, cn } from "@/lib/utils";

/* ═══════════════════════════════════════════════════════════════════════════
   CPR TRADING COMMAND CENTER
   Everything you need for intraday CPR breakout trading — one page.
   ═══════════════════════════════════════════════════════════════════════════ */

export default function TradingCommandCenter() {
  const [authMsg, setAuthMsg] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // Handle Zerodha redirect auth result
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

  return (
    <div className="p-6 lg:p-8 space-y-6 max-w-[1800px] mx-auto">
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

      {/* ── Section 1: Status Bar ────────────────────────────── */}
      <StatusBar />

      {/* ── Section 2: CPR Scanner (compact) ─────────────────── */}
      <CPRScannerSection />

      {/* ── Section 3: Engine Control ────────────────────────── */}
      <EngineControlPanel />

      {/* ── Section 4: Positions + Risk side by side ─────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3">
          <PositionsPanel />
        </div>
        <div className="lg:col-span-2 space-y-6">
          <RiskMonitor />
          <RecentOrders />
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SECTION 1 — STATUS BAR
   Auth status, Daily P&L, Kill Switch, Active Positions count
   ═══════════════════════════════════════════════════════════════════════════ */

function StatusBar() {
  const { data: risk } = useRiskStatus();
  const { data: positions } = usePositions();
  const { data: strats } = useStrategies();
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

  return (
    <div className="flex flex-col gap-4">
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
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {/* Daily P&L */}
        <div className="card !p-4">
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
            Daily P&L
          </p>
          <p
            className={cn(
              "text-xl font-bold mt-1",
              risk
                ? risk.daily_pnl >= 0
                  ? "text-emerald-400"
                  : "text-red-400"
                : ""
            )}
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {risk ? formatPnl(risk.daily_pnl) : "--"}
          </p>
        </div>

        {/* Loss Remaining */}
        <div className="card !p-4">
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
            Loss Budget Left
          </p>
          <p
            className="text-xl font-bold mt-1"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {risk ? formatCurrency(risk.daily_loss_remaining) : "--"}
          </p>
          {risk && risk.daily_loss_limit > 0 && (
            <div className="mt-1.5 h-1 rounded-full bg-white/5 overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all",
                  risk.daily_loss / risk.daily_loss_limit > 0.8
                    ? "bg-red-500"
                    : risk.daily_loss / risk.daily_loss_limit > 0.5
                      ? "bg-amber-500"
                      : "bg-emerald-500"
                )}
                style={{
                  width: `${Math.min((risk.daily_loss / risk.daily_loss_limit) * 100, 100)}%`,
                }}
              />
            </div>
          )}
        </div>

        {/* Open Positions */}
        <div className="card !p-4">
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
            Open Positions
          </p>
          <p
            className="text-xl font-bold mt-1"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {openPositionCount}
          </p>
        </div>

        {/* Active Strategies */}
        <div className="card !p-4">
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
            Running Strategies
          </p>
          <p
            className="text-xl font-bold mt-1"
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            {runningStrategies}
          </p>
        </div>

        {/* Kill Switch */}
        <div className="card !p-4">
          <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
            Kill Switch
          </p>
          <button
            onClick={handleKillSwitch}
            className={cn(
              "mt-1 text-sm font-bold px-3 py-1 rounded-md transition-all",
              isKillActive
                ? "bg-red-500/20 text-red-400 border border-red-500/40 hover:bg-red-500/30"
                : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20"
            )}
          >
            {isKillActive ? "!! ACTIVE — Click to OFF" : "OFF"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SECTION 2 — CPR SCANNER (INLINE)
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

  // Index checklist
  const [availableIndices, setAvailableIndices] = useState<CPRIndexInfo[]>([]);
  const [selectedIndices, setSelectedIndices] = useState<Set<string>>(
    new Set()
  );
  const [indicesLoading, setIndicesLoading] = useState(true);

  // Load available indices on mount
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
      {/* Scanner Header — always visible */}
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
            {/* Controls row */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 pt-4">
              {/* Date */}
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
              {/* Threshold */}
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
              {/* Scan button */}
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

            {/* Index checklist — compact */}
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

      {/* Results — Today's Picks + Full Grouped Results */}
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

  // Determine best index — the one with the most narrow stocks
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

  // Top 5 picks: narrowest CPR stocks overall
  const topPicks = stocks.filter((s) => s.cpr.is_narrow).slice(0, 5);

  const handleLoadToEngine = async () => {
    if (topPicks.length === 0) return;
    setLoadingEngine(true);
    setLoadResult(null);
    try {
      const picks = topPicks.map((s) => {
        // Determine direction
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
          quantity: 1,
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
      {/* Data source + summary bar */}
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

      {/* ── TODAY'S TOP PICKS ───────────────────────────────── */}
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

      {/* ── FULL RESULTS BY INDEX (collapsible) ─────────────── */}
      {stocks.length > 0 && (
        <FullResultsPanel stocks={stocks} indices={result.scan_params.indices_selected} errors={result.errors} />
      )}
    </div>
  );
}

/* ── Top Pick Row ─────────────────────────────────────────────────────── */

function TopPickRow({ stock, rank }: { stock: CPRStockEntry; rank: number }) {
  const { cpr, prev_day } = stock;

  // Signal direction based on today's open vs CPR levels
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

  // Build groups
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
          {/* Errors */}
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

          {/* Index groups */}
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
      {/* Group header */}
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

      {/* Compact stock list */}
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
   SECTION 3 — ENGINE CONTROL PANEL
   Engine state, start/stop/pause, loaded picks with strategy status,
   and a live event feed.
   ═══════════════════════════════════════════════════════════════════════════ */

function EngineControlPanel() {
  const { data: swrStatus, mutate: mutateStatus } = useEngineStatus();
  const { data: swrEvents } = useEngineEvents(30);
  const {
    connected: wsConnected,
    status: wsStatus,
    events: wsEvents,
  } = useEngineStream();
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);

  // Prefer WebSocket data when connected, fall back to SWR polling
  const status = wsConnected && wsStatus ? wsStatus : swrStatus;
  const events = wsConnected && wsEvents.length > 0 ? wsEvents : (swrEvents ?? swrStatus?.recent_events ?? []);

  const state = status?.state ?? "idle";
  const isRunning = state === "running";
  const isPaused = state === "paused";
  const hasPicks = (status?.picks_count ?? 0) > 0;

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
      {/* Header with state badge + controls */}
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
          {hasPicks && (
            <span className="text-xs text-[var(--muted)]">
              {status!.picks_count} picks loaded
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* WebSocket connection indicator */}
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
              {/* Start */}
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
              {/* Pause / Resume */}
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
              {/* Stop */}
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
            {/* Metrics summary */}
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

          {/* Two columns: Strategies + Events */}
          {hasPicks && (
            <div className="grid grid-cols-1 lg:grid-cols-5 divide-y lg:divide-y-0 lg:divide-x divide-[var(--card-border)]">
              {/* Strategies / Picks */}
              <div className="lg:col-span-3 p-4">
                <EngineStrategiesTable strategies={status?.strategies ?? {}} />
              </div>
              {/* Event Feed */}
              <div className="lg:col-span-2 p-4">
                <EngineEventFeed events={events} />
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
}: {
  strategies: Record<string, EngineStrategyDetail>;
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
              <th className="text-right py-2 px-2">Entry</th>
              <th className="text-right py-2 px-2">SL</th>
              <th className="text-right py-2 px-2">Target</th>
              <th className="text-right py-2 pl-2">P&L</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([token, s]) => (
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
                    s.metrics.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"
                  )}
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  {s.metrics.total_pnl !== 0
                    ? formatPnl(s.metrics.total_pnl)
                    : "--"}
                </td>
              </tr>
            ))}
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
  const config: Record<string, { color: string; symbol: string }> = {
    signal: { color: "text-blue-400", symbol: "~" },
    order: { color: "text-amber-400", symbol: "$" },
    fill: { color: "text-emerald-400", symbol: "+" },
    exit: { color: "text-orange-400", symbol: "-" },
    error: { color: "text-red-400", symbol: "!" },
    scan: { color: "text-purple-400", symbol: "#" },
    info: { color: "text-[var(--muted)]", symbol: ">" },
  };
  const c = config[type] ?? config.info;
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

/* ═══════════════════════════════════════════════════════════════════════════
   SECTION 4 — POSITIONS PANEL
   Current MIS intraday positions with live P&L
   ═══════════════════════════════════════════════════════════════════════════ */

function PositionsPanel() {
  const { data, isLoading } = usePositions();
  const positions = data?.net ?? [];

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold">Open Positions</h3>
        {positions.length > 0 && (
          <span
            className={cn(
              "text-sm font-bold",
              totalPnl >= 0 ? "text-emerald-400" : "text-red-400"
            )}
            style={{ fontFamily: "'JetBrains Mono', monospace" }}
          >
            Total: {formatPnl(totalPnl)}
          </span>
        )}
      </div>

      {isLoading && (
        <p className="text-[var(--muted)] text-sm">Loading...</p>
      )}

      {!isLoading && positions.length === 0 && (
        <div className="text-center py-8">
          <p className="text-[var(--muted)] text-sm">No open positions</p>
          <p className="text-[10px] text-[var(--muted)] mt-1">
            Positions will appear here when you enter a trade
          </p>
        </div>
      )}

      {positions.length > 0 && (
        <div className="space-y-2">
          {positions.map((p) => (
            <div
              key={p.trading_symbol}
              className="flex items-center justify-between py-3 px-4 rounded-lg bg-white/[0.02] border border-[var(--card-border)]"
            >
              <div className="flex items-center gap-3">
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
                <div>
                  <span className="font-medium text-sm">
                    {p.trading_symbol}
                  </span>
                  <span className="text-xs text-[var(--muted)] ml-2">
                    {p.exchange}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-6">
                <div
                  className="text-right text-xs text-[var(--muted)]"
                  style={{ fontFamily: "'JetBrains Mono', monospace" }}
                >
                  <div>
                    Qty: {Math.abs(p.quantity)} @ {formatNumber(p.average_price)}
                  </div>
                  <div>LTP: {formatNumber(p.last_price)}</div>
                </div>
                <span
                  className={cn(
                    "text-sm font-bold min-w-[80px] text-right",
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
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SECTION 5 — RISK MONITOR
   ═══════════════════════════════════════════════════════════════════════════ */

function RiskMonitor() {
  const { data: risk } = useRiskStatus();

  if (!risk) return null;

  const lossPercent =
    risk.daily_loss_limit > 0
      ? (risk.daily_loss / risk.daily_loss_limit) * 100
      : 0;

  return (
    <div className="card">
      <h3 className="text-sm font-semibold mb-4">Risk Monitor</h3>
      <div className="space-y-4">
        {/* Daily Loss Progress */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span className="text-[var(--muted)]">Daily Loss Used</span>
            <span
              className="text-[var(--muted)]"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              {formatCurrency(risk.daily_loss)} /{" "}
              {formatCurrency(risk.daily_loss_limit)}
            </span>
          </div>
          <div className="h-2 rounded-full bg-white/5 overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                lossPercent > 80
                  ? "bg-red-500"
                  : lossPercent > 50
                    ? "bg-amber-500"
                    : "bg-emerald-500"
              )}
              style={{ width: `${Math.min(lossPercent, 100)}%` }}
            />
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
              Order Rate
            </p>
            <p
              className="text-sm font-bold mt-0.5"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              {risk.orders_last_minute}/{risk.order_rate_limit}
              <span className="text-[10px] text-[var(--muted)] ml-1">
                /min
              </span>
            </p>
          </div>
          <div>
            <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
              Loss Remaining
            </p>
            <p
              className={cn(
                "text-sm font-bold mt-0.5",
                risk.daily_loss_remaining < 10000
                  ? "text-red-400"
                  : "text-emerald-400"
              )}
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              {formatCurrency(risk.daily_loss_remaining)}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SECTION 6 — RECENT ORDERS
   ═══════════════════════════════════════════════════════════════════════════ */

function RecentOrders() {
  const { data, isLoading } = useOrders();
  const recentOrders = data?.slice(-8).reverse() ?? [];

  return (
    <div className="card">
      <h3 className="text-sm font-semibold mb-4">Recent Orders</h3>

      {isLoading && (
        <p className="text-[var(--muted)] text-sm">Loading...</p>
      )}

      {!isLoading && recentOrders.length === 0 && (
        <p className="text-[var(--muted)] text-xs text-center py-4">
          No orders today
        </p>
      )}

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
    </div>
  );
}

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
