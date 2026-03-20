"use client";

import { useState, useEffect, useCallback } from "react";
import {
  backtest,
  type CPRScanParams,
  type CPRScanResult,
  type CPRStockEntry,
  type CPRIndexInfo,
} from "@/lib/api";
import { formatNumber } from "@/lib/utils";

/* ────────── Constants ────────── */
const DEFAULT_VISIBLE = 5;

/* ────────── Page ────────── */

export default function CPRScannerPage() {
  const [scanDate, setScanDate] = useState(
    () => new Date().toISOString().split("T")[0]
  );
  const [threshold, setThreshold] = useState(0.5);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<CPRScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Index checklist
  const [availableIndices, setAvailableIndices] = useState<CPRIndexInfo[]>([]);
  const [selectedIndices, setSelectedIndices] = useState<Set<string>>(new Set());
  const [indicesLoading, setIndicesLoading] = useState(true);

  // Load available indices on mount
  useEffect(() => {
    backtest
      .cprIndices()
      .then((data) => {
        setAvailableIndices(data.indices);
        // Select all indices with constituents by default
        const withStocks = data.indices
          .filter((i) => i.constituent_count > 0)
          .map((i) => i.name);
        setSelectedIndices(new Set(withStocks));
      })
      .catch(() => {
        // Fallback: hardcoded list
        const fallback = [
          "NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY FIN SERVICE",
          "NIFTY PHARMA", "NIFTY AUTO", "NIFTY FMCG", "NIFTY ENERGY",
          "NIFTY INFRA", "NIFTY PSU BANK",
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
    setSelectedIndices(new Set(availableIndices.map((i) => i.name)));
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
    <div className="p-8 space-y-6 max-w-[1600px]">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight">CPR Scanner</h2>
        <p className="text-[var(--muted)] text-sm mt-1">
          Scan constituent stocks of NIFTY indices for narrow CPR — ranked by
          width for breakout potential
        </p>
      </div>

      {/* Controls */}
      <div className="card">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Scan Date */}
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              Scan Date
            </label>
            <input
              type="date"
              className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
              value={scanDate}
              onChange={(e) => setScanDate(e.target.value)}
            />
            <p className="text-[10px] text-[var(--muted)] mt-0.5">
              CPR is calculated from previous trading day&apos;s OHLC
            </p>
          </div>

          {/* Threshold */}
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1.5 uppercase tracking-wider">
              Narrow Threshold %
            </label>
            <input
              type="number"
              className="w-full bg-[var(--background)] border border-[var(--card-border)] rounded-lg px-3 py-2 text-sm"
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              min={0.05}
              max={5}
              step={0.05}
            />
            <p className="text-[10px] text-[var(--muted)] mt-0.5">
              CPR width as % of pivot — lower = narrower
            </p>
          </div>

          {/* Run */}
          <div className="flex items-end">
            <button
              className="btn-primary px-8 py-2.5 w-full md:w-auto"
              onClick={handleScan}
              disabled={running || selectedIndices.size === 0}
            >
              {running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Scanning {selectedIndices.size} indices…
                </span>
              ) : (
                `⊡ Scan ${selectedIndices.size} Indices`
              )}
            </button>
          </div>
        </div>

        {/* Index Checklist */}
        <div className="mt-6 pt-6 border-t border-[var(--card-border)]">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs text-[var(--muted)] uppercase tracking-wider">
              Select Indices
            </h4>
            <div className="flex gap-2">
              <button
                className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                onClick={selectAll}
              >
                Select All
              </button>
              <span className="text-[var(--card-border)]">|</span>
              <button
                className="text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                onClick={selectNone}
              >
                Clear All
              </button>
            </div>
          </div>

          {indicesLoading ? (
            <p className="text-xs text-[var(--muted)]">Loading indices…</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2">
              {availableIndices.map((idx) => {
                const checked = selectedIndices.has(idx.name);
                const hasStocks = idx.constituent_count > 0;
                return (
                  <label
                    key={idx.name}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm cursor-pointer transition-all select-none ${
                      checked
                        ? "border-brand-500/50 bg-brand-500/10 text-white"
                        : hasStocks
                          ? "border-[var(--card-border)] text-[var(--muted)] hover:border-white/20"
                          : "border-[var(--card-border)] text-[var(--muted)]/40 opacity-50 cursor-not-allowed"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!hasStocks}
                      onChange={() => toggleIndex(idx.name)}
                      className="w-3.5 h-3.5 rounded accent-blue-500"
                    />
                    <span className="text-xs truncate">{idx.name}</span>
                    <span className="text-[10px] text-[var(--muted)] ml-auto">
                      {idx.constituent_count}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        {error && (
          <p className="text-sm text-red-400 mt-4">{error}</p>
        )}
      </div>

      {/* Results */}
      {result && <ScanResults result={result} />}
    </div>
  );
}

/* ────────── Results ────────── */

function ScanResults({ result }: { result: CPRScanResult }) {
  const stocks = result.stocks;

  // Determine data source
  const sources = new Set(stocks.map((s) => s.data_source));
  const isMock = sources.has("mock_synthetic");

  return (
    <div className="space-y-4">
      {/* Data source banner */}
      <div
        className={`rounded-lg px-4 py-2 text-sm flex items-center gap-2 ${
          isMock
            ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
            : stocks.length > 0
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
              : "bg-gray-500/10 text-[var(--muted)] border border-[var(--card-border)]"
        }`}
      >
        {isMock ? (
          <>
            <span>⚠</span> Scanned with{" "}
            <strong>synthetic mock data</strong> — connect Zerodha for real
            results
          </>
        ) : stocks.length > 0 ? (
          <>
            <span>✓</span> Scanned with{" "}
            <strong>real Zerodha market data</strong>
          </>
        ) : (
          <>
            <span>--</span> No stock data available
          </>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <SummaryCard
          label="Scan Date"
          value={result.scan_date}
        />
        <SummaryCard
          label="Stocks Scanned"
          value={String(result.summary.total_stocks_scanned)}
        />
        <SummaryCard
          label="Narrow CPR"
          value={String(result.summary.narrow_count)}
          highlight={result.summary.narrow_count > 0}
        />
        <SummaryCard
          label="Unique Stocks"
          value={String(result.scan_params.unique_stocks)}
        />
      </div>

      {/* Scan Parameters */}
      <div className="card !p-4">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-[var(--muted)]">
          <span>
            Threshold:{" "}
            <span className="text-white">
              {result.scan_params.narrow_threshold}%
            </span>
          </span>
          <span>
            Indices:{" "}
            <span className="text-white">
              {result.scan_params.indices_selected.join(", ")}
            </span>
          </span>
        </div>
      </div>

      {/* Errors */}
      {result.errors && result.errors.length > 0 && (
        <ErrorsPanel errors={result.errors} />
      )}

      {/* Stock Ranking Table — grouped by index */}
      {stocks.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-[var(--muted)] text-sm">
            No stocks found for this scan.
          </p>
          <p className="text-xs text-[var(--muted)] mt-1">
            Ensure the mock sample data is loaded, or connect to Zerodha.
          </p>
        </div>
      ) : (
        <IndexGroupedResults
          stocks={stocks}
          indices={result.scan_params.indices_selected}
        />
      )}
    </div>
  );
}

/* ────────── Index-Grouped Results ────────── */

function IndexGroupedResults({
  stocks,
  indices,
}: {
  stocks: CPRStockEntry[];
  indices: string[];
}) {
  // Build a map: index name → stocks belonging to that index, sorted by CPR width ascending
  const groupMap = new Map<string, CPRStockEntry[]>();

  for (const indexName of indices) {
    const matching = stocks
      .filter((s) => s.indices.includes(indexName))
      .sort((a, b) => a.cpr.width_pct - b.cpr.width_pct);
    if (matching.length > 0) {
      groupMap.set(indexName, matching);
    }
  }

  // Sort index groups by their top stock's narrowest CPR width
  const sortedGroups = Array.from(groupMap.entries()).sort(
    ([, a], [, b]) => a[0].cpr.width_pct - b[0].cpr.width_pct
  );

  if (sortedGroups.length === 0) {
    return (
      <div className="card text-center py-12">
        <p className="text-[var(--muted)] text-sm">
          No stocks matched the selected indices.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--muted)]">
          Results by Index
        </h3>
        <span className="text-xs text-[var(--muted)]">
          {sortedGroups.length} {sortedGroups.length === 1 ? "index" : "indices"} · {stocks.length} stocks total
        </span>
      </div>
      {sortedGroups.map(([indexName, indexStocks]) => (
        <IndexGroup
          key={indexName}
          indexName={indexName}
          stocks={indexStocks}
        />
      ))}
    </div>
  );
}

/* ────────── Single Index Group ────────── */

function IndexGroup({
  indexName,
  stocks,
}: {
  indexName: string;
  stocks: CPRStockEntry[];
}) {
  const [expanded, setExpanded] = useState(true);
  const [showAll, setShowAll] = useState(false);

  const narrowCount = stocks.filter((s) => s.cpr.is_narrow).length;
  const visible = showAll ? stocks : stocks.slice(0, DEFAULT_VISIBLE);
  const hiddenCount = stocks.length - DEFAULT_VISIBLE;

  // Color coding for the index badge based on narrowest stock
  const narrowestPct = stocks[0]?.cpr.width_pct ?? 999;
  const badgeColor =
    narrowestPct < 0.3
      ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/25"
      : narrowestPct < 0.5
        ? "bg-blue-500/15 text-blue-400 border-blue-500/25"
        : "bg-white/5 text-[var(--muted)] border-[var(--card-border)]";

  return (
    <div className="card !p-0 overflow-hidden">
      {/* Group Header — clickable to expand/collapse */}
      <button
        className="w-full px-6 py-3.5 flex items-center justify-between bg-white/[0.02] hover:bg-white/[0.04] transition-colors border-b border-[var(--card-border)]"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-[var(--muted)] text-xs transition-transform duration-200"
            style={{ transform: expanded ? "rotate(90deg)" : "rotate(0deg)" }}
          >
            ▶
          </span>
          <span className="text-sm font-semibold tracking-tight">{indexName}</span>
          <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-medium border ${badgeColor}`}>
            {stocks.length} {stocks.length === 1 ? "stock" : "stocks"}
          </span>
          {narrowCount > 0 && (
            <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400">
              {narrowCount} narrow
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-[var(--muted)]">
          <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>
            narrowest: {narrowestPct.toFixed(3)}%
          </span>
        </div>
      </button>

      {/* Stocks Table */}
      {expanded && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[var(--muted)] text-[10px] uppercase tracking-wider border-b border-[var(--card-border)]">
                  <th className="text-left py-2 pl-6 pr-2 w-10">#</th>
                  <th className="text-left py-2 px-2">Stock</th>
                  <th className="text-right py-2 px-2">Prev Close</th>
                  <th className="text-right py-2 px-2">Today Open</th>
                  <th className="text-right py-2 px-2">Pivot</th>
                  <th className="text-right py-2 px-2">TC</th>
                  <th className="text-right py-2 px-2">BC</th>
                  <th className="text-right py-2 px-2">Width</th>
                  <th className="text-right py-2 px-2">Width %</th>
                  <th className="text-center py-2 px-2 pr-6">Status</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((stock, idx) => (
                  <GroupedStockRow
                    key={stock.instrument_token}
                    stock={stock}
                    rank={idx + 1}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* Show More / Less */}
          {stocks.length > DEFAULT_VISIBLE && (
            <div className="px-6 py-2.5 border-t border-[var(--card-border)] bg-white/[0.02]">
              <button
                className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                onClick={() => setShowAll(!showAll)}
              >
                {showAll
                  ? "Show less"
                  : `Show ${hiddenCount} more stock${hiddenCount !== 1 ? "s" : ""}…`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ────────── Grouped Stock Row (no Index column) ────────── */

function GroupedStockRow({
  stock,
  rank,
}: {
  stock: CPRStockEntry;
  rank: number;
}) {
  const { cpr, prev_day } = stock;
  const isNarrow = cpr.is_narrow;

  return (
    <tr
      className={`border-t border-[var(--card-border)] transition-colors ${
        isNarrow
          ? "bg-emerald-500/[0.04] hover:bg-emerald-500/[0.08]"
          : "hover:bg-white/[0.03]"
      }`}
    >
      {/* Rank */}
      <td
        className="py-2.5 pl-6 pr-2 font-medium text-[var(--muted)]"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {rank}
      </td>

      {/* Stock Name + other index memberships */}
      <td className="py-2.5 px-2">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm">{stock.symbol}</span>
          <span className="text-xs text-[var(--muted)] hidden lg:inline">{stock.name}</span>
          {stock.data_source === "mock_synthetic" && (
            <span className="text-[10px] text-amber-400/60">mock</span>
          )}
          {/* Show other indices this stock belongs to */}
          {stock.indices.length > 1 && (
            <span className="text-[10px] text-[var(--muted)] opacity-60">
              +{stock.indices.length - 1} {stock.indices.length - 1 === 1 ? "index" : "indices"}
            </span>
          )}
        </div>
      </td>

      {/* Prev Close */}
      <td
        className="py-2.5 px-2 text-right text-[var(--muted)]"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(prev_day.close)}
      </td>

      {/* Today Open */}
      <td
        className="py-2.5 px-2 text-right"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(stock.today_open)}
      </td>

      {/* CPR Values */}
      <td
        className="py-2.5 px-2 text-right font-medium"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(cpr.pivot)}
      </td>
      <td
        className="py-2.5 px-2 text-right text-blue-400"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(cpr.tc)}
      </td>
      <td
        className="py-2.5 px-2 text-right text-orange-400"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(cpr.bc)}
      </td>

      {/* Width */}
      <td
        className="py-2.5 px-2 text-right"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {formatNumber(cpr.width)}
      </td>

      {/* Width % */}
      <td
        className={`py-2.5 px-2 text-right font-semibold ${
          isNarrow ? "text-emerald-400" : "text-[var(--muted)]"
        }`}
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {cpr.width_pct.toFixed(3)}%
      </td>

      {/* Status */}
      <td className="py-2.5 px-2 pr-6 text-center">
        {isNarrow ? (
          <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 uppercase tracking-wider">
            Narrow
          </span>
        ) : (
          <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-medium bg-gray-500/10 text-gray-500 uppercase tracking-wider">
            Wide
          </span>
        )}
      </td>
    </tr>
  );
}

/* ────────── Errors Panel ────────── */

function ErrorsPanel({
  errors,
}: {
  errors: { symbol: string; error: string }[];
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-lg px-4 py-3 bg-red-500/10 border border-red-500/20">
      <button
        className="w-full flex items-center justify-between"
        onClick={() => setExpanded(!expanded)}
      >
        <p className="text-sm font-medium text-red-400">
          {errors.length} scan {errors.length === 1 ? "error" : "errors"}
        </p>
        <span className="text-xs text-red-400/60">
          {expanded ? "Hide" : "Show"}
        </span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1">
          {errors.map((err, i) => (
            <p key={i} className="text-xs text-red-400/80">
              <span className="font-medium">{err.symbol}</span>:{" "}
              {err.error}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/* ────────── Summary Card ────────── */

function SummaryCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="card !p-4">
      <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">
        {label}
      </p>
      <p
        className={`text-xl font-semibold mt-1 ${
          highlight ? "text-emerald-400" : ""
        }`}
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {value}
      </p>
    </div>
  );
}
