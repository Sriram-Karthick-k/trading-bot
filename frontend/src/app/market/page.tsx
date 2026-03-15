"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { market as marketApi } from "@/lib/api";
import { formatCurrency, formatNumber, formatPercent, cn } from "@/lib/utils";
import type { Instrument, Candle, Quote } from "@/types";

const INTERVALS = [
  { label: "1m", value: "minute" },
  { label: "5m", value: "5minute" },
  { label: "15m", value: "15minute" },
  { label: "1H", value: "60minute" },
  { label: "1D", value: "day" },
] as const;

const RANGES = [
  { label: "1D", days: 1 },
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "1Y", days: 365 },
] as const;

function formatDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function MarketPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Instrument[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Instrument | null>(null);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (value.length < 1) {
      setResults([]);
      setShowDropdown(false);
      return;
    }
    setSearching(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await marketApi.searchInstruments(value);
        setResults(data);
        setShowDropdown(true);
      } catch {
        // Try full instruments list as fallback
        try {
          const all = await marketApi.getInstruments();
          const q = value.toUpperCase();
          setResults(
            all
              .filter(
                (i) =>
                  i.trading_symbol.toUpperCase().includes(q) ||
                  (i.name || "").toUpperCase().includes(q),
              )
              .slice(0, 30),
          );
          setShowDropdown(true);
        } catch {
          setResults([]);
        }
      } finally {
        setSearching(false);
      }
    }, 250);
  }, []);

  const selectInstrument = (inst: Instrument) => {
    setSelected(inst);
    setQuery(inst.trading_symbol);
    setShowDropdown(false);
  };

  return (
    <div className="p-8 space-y-6">
      <header>
        <h2 className="text-2xl font-bold tracking-tight">Market</h2>
        <p className="text-[var(--muted)] text-sm mt-1">
          Search stocks and view performance
        </p>
      </header>

      {/* Search */}
      <div ref={searchRef} className="relative max-w-2xl">
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)] text-lg">
            ⌕
          </span>
          <input
            className="input w-full pl-10 py-3 text-base"
            value={query}
            onChange={(e) => handleSearch(e.target.value)}
            onFocus={() => results.length > 0 && setShowDropdown(true)}
            placeholder="Search by symbol or company name..."
            autoComplete="off"
          />
          {searching && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--muted)]">
              searching...
            </span>
          )}
        </div>

        {showDropdown && results.length > 0 && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-[var(--card)] border border-[var(--card-border)] rounded-lg shadow-2xl max-h-80 overflow-y-auto">
            {results.map((inst) => (
              <button
                key={`${inst.exchange}-${inst.trading_symbol}-${inst.instrument_token}`}
                className="w-full text-left px-4 py-3 hover:bg-white/5 flex items-center justify-between border-b border-[var(--card-border)] last:border-0 transition-colors"
                onClick={() => selectInstrument(inst)}
              >
                <div>
                  <span className="font-medium text-sm">{inst.trading_symbol}</span>
                  <span className="text-xs text-[var(--muted)] ml-2">{inst.exchange}</span>
                  {inst.name && (
                    <p className="text-xs text-[var(--muted)] mt-0.5">{inst.name}</p>
                  )}
                </div>
                <div className="text-right">
                  {inst.last_price ? (
                    <span className="text-sm font-mono">
                      ₹{formatNumber(inst.last_price)}
                    </span>
                  ) : (
                    <span className="text-xs text-[var(--muted)]">
                      {inst.instrument_type || "EQ"}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}

        {showDropdown && query.length >= 1 && results.length === 0 && !searching && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-[var(--card)] border border-[var(--card-border)] rounded-lg shadow-2xl p-4">
            <p className="text-sm text-[var(--muted)] text-center">
              No instruments found for &ldquo;{query}&rdquo;
            </p>
          </div>
        )}
      </div>

      {/* Selected Instrument Details */}
      {selected ? (
        <StockDetail instrument={selected} />
      ) : (
        <div className="card flex flex-col items-center justify-center py-16 text-center">
          <span className="text-4xl mb-4 opacity-20">⌕</span>
          <p className="text-[var(--muted)] text-sm">
            Search for a stock to view its price history and details
          </p>
        </div>
      )}
    </div>
  );
}

function StockDetail({ instrument }: { instrument: Instrument }) {
  const [candles, setCandles] = useState<Candle[]>([]);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [interval, setInterval] = useState("day");
  const [range, setRange] = useState(30);
  const [loading, setLoading] = useState(false);

  // Fetch quote
  useEffect(() => {
    const key = `${instrument.exchange}:${instrument.trading_symbol}`;
    marketApi
      .getQuote([key])
      .then((data) => {
        const q = data[key];
        if (q) setQuote(q);
      })
      .catch(() => {});
  }, [instrument]);

  // Fetch historical candles
  useEffect(() => {
    setLoading(true);
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - range);

    marketApi
      .getHistorical(
        instrument.instrument_token,
        interval,
        formatDate(from),
        formatDate(to),
      )
      .then(setCandles)
      .catch(() => setCandles([]))
      .finally(() => setLoading(false));
  }, [instrument.instrument_token, interval, range]);

  const lastPrice = quote?.last_price ?? instrument.last_price ?? 0;
  const prevClose = quote?.ohlc_close ?? 0;
  const change = prevClose > 0 ? lastPrice - prevClose : 0;
  const changePct = prevClose > 0 ? (change / prevClose) * 100 : 0;
  const isPositive = change >= 0;

  return (
    <div className="space-y-6">
      {/* Header card */}
      <div className="card">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h3 className="text-xl font-bold">{instrument.trading_symbol}</h3>
              <span className="badge-info">{instrument.exchange}</span>
              {instrument.instrument_type && (
                <span className="text-xs text-[var(--muted)]">{instrument.instrument_type}</span>
              )}
            </div>
            {instrument.name && (
              <p className="text-sm text-[var(--muted)] mt-1">{instrument.name}</p>
            )}
          </div>
          <div className="text-right">
            <p
              className="text-2xl font-bold font-mono"
              style={{ fontFamily: "'JetBrains Mono', monospace" }}
            >
              {formatCurrency(lastPrice)}
            </p>
            {prevClose > 0 && (
              <p
                className={cn(
                  "text-sm font-mono mt-1",
                  isPositive ? "pnl-positive" : "pnl-negative",
                )}
              >
                {isPositive ? "▲" : "▼"} {formatNumber(Math.abs(change))} (
                {formatPercent(changePct)})
              </p>
            )}
          </div>
        </div>

        {/* Quote details grid */}
        {quote && (
          <div className="grid grid-cols-6 gap-4 mt-6 pt-4 border-t border-[var(--card-border)]">
            <QuoteStat label="Open" value={formatNumber(quote.ohlc_open)} />
            <QuoteStat label="High" value={formatNumber(quote.ohlc_high)} />
            <QuoteStat label="Low" value={formatNumber(quote.ohlc_low)} />
            <QuoteStat label="Prev Close" value={formatNumber(quote.ohlc_close)} />
            <QuoteStat label="Volume" value={formatVolume(quote.volume)} />
            {quote.oi !== undefined && quote.oi > 0 && (
              <QuoteStat label="OI" value={formatVolume(quote.oi)} />
            )}
          </div>
        )}
      </div>

      {/* Chart controls */}
      <div className="flex items-center gap-4">
        <div className="flex gap-1 bg-[var(--card)] rounded-lg p-1 border border-[var(--card-border)]">
          {INTERVALS.map((i) => (
            <button
              key={i.value}
              className={cn(
                "px-3 py-1.5 text-xs rounded-md transition-colors",
                interval === i.value
                  ? "bg-brand-600 text-white"
                  : "text-[var(--muted)] hover:text-white hover:bg-white/5",
              )}
              onClick={() => setInterval(i.value)}
            >
              {i.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1 bg-[var(--card)] rounded-lg p-1 border border-[var(--card-border)]">
          {RANGES.map((r) => (
            <button
              key={r.days}
              className={cn(
                "px-3 py-1.5 text-xs rounded-md transition-colors",
                range === r.days
                  ? "bg-brand-600 text-white"
                  : "text-[var(--muted)] hover:text-white hover:bg-white/5",
              )}
              onClick={() => setRange(r.days)}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Candle chart */}
      <div className="card p-0 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <p className="text-sm text-[var(--muted)]">Loading chart data...</p>
          </div>
        ) : candles.length === 0 ? (
          <div className="flex items-center justify-center py-24">
            <p className="text-sm text-[var(--muted)]">
              No historical data available for this range
            </p>
          </div>
        ) : (
          <CandleChart candles={candles} />
        )}
      </div>

      {/* Candle data table */}
      {candles.length > 0 && (
        <div className="card overflow-hidden p-0">
          <div className="p-4 border-b border-[var(--card-border)]">
            <h4 className="text-sm font-semibold">
              Price History{" "}
              <span className="text-[var(--muted)] font-normal">
                ({candles.length} records)
              </span>
            </h4>
          </div>
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-[var(--card)]">
                <tr className="border-b border-[var(--card-border)]">
                  <th className="text-left p-3 text-xs text-[var(--muted)] font-medium">
                    Date
                  </th>
                  <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">
                    Open
                  </th>
                  <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">
                    High
                  </th>
                  <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">
                    Low
                  </th>
                  <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">
                    Close
                  </th>
                  <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">
                    Volume
                  </th>
                </tr>
              </thead>
              <tbody>
                {candles
                  .slice()
                  .reverse()
                  .slice(0, 100)
                  .map((c, i) => {
                    const isUp = c.close >= c.open;
                    return (
                      <tr
                        key={i}
                        className="border-b border-[var(--card-border)] hover:bg-white/[0.02]"
                      >
                        <td className="p-3 text-xs text-[var(--muted)]">
                          {new Date(c.timestamp).toLocaleDateString("en-IN", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })}
                        </td>
                        <td className="p-3 text-right font-mono">
                          {formatNumber(c.open)}
                        </td>
                        <td className="p-3 text-right font-mono text-emerald-400">
                          {formatNumber(c.high)}
                        </td>
                        <td className="p-3 text-right font-mono text-red-400">
                          {formatNumber(c.low)}
                        </td>
                        <td
                          className={cn(
                            "p-3 text-right font-mono font-medium",
                            isUp ? "text-emerald-400" : "text-red-400",
                          )}
                        >
                          {formatNumber(c.close)}
                        </td>
                        <td className="p-3 text-right font-mono text-xs">
                          {formatVolume(c.volume)}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function QuoteStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="text-sm font-mono font-medium mt-0.5">{value}</p>
    </div>
  );
}

function formatVolume(v: number): string {
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`;
  if (v >= 1_00_000) return `${(v / 1_00_000).toFixed(2)}L`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toLocaleString("en-IN");
}

/* ─── Canvas Candle Chart ─────────────────────────────────────── */

function CandleChart({ candles }: { candles: Candle[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || candles.length === 0) return;

    const dpr = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    const height = 360;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    // Colors
    const upColor = "#10b981";
    const downColor = "#ef4444";
    const gridColor = "rgba(255,255,255,0.04)";
    const textColor = "rgba(255,255,255,0.3)";

    const pad = { top: 20, right: 70, bottom: 30, left: 10 };
    const chartW = width - pad.left - pad.right;
    const chartH = height - pad.top - pad.bottom;

    // Data range
    const prices = candles.flatMap((c) => [c.high, c.low]);
    let minP = Math.min(...prices);
    let maxP = Math.max(...prices);
    const priceRange = maxP - minP || 1;
    minP -= priceRange * 0.05;
    maxP += priceRange * 0.05;

    const toY = (p: number) =>
      pad.top + chartH - ((p - minP) / (maxP - minP)) * chartH;

    // Clear
    ctx.fillStyle = "#141414";
    ctx.fillRect(0, 0, width, height);

    // Grid lines
    const gridLines = 5;
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.fillStyle = textColor;
    ctx.textAlign = "right";
    for (let i = 0; i <= gridLines; i++) {
      const price = minP + ((maxP - minP) * i) / gridLines;
      const y = toY(price);
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(width - pad.right, y);
      ctx.stroke();
      ctx.fillText(`₹${price.toFixed(2)}`, width - 8, y + 3);
    }

    // Candles
    const maxCandles = Math.min(candles.length, 200);
    const visibleCandles = candles.slice(-maxCandles);
    const candleWidth = Math.max(1, (chartW / maxCandles) * 0.7);
    const gap = chartW / maxCandles;

    visibleCandles.forEach((c, i) => {
      const x = pad.left + i * gap + gap / 2;
      const isUp = c.close >= c.open;
      const color = isUp ? upColor : downColor;

      // Wick
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, toY(c.high));
      ctx.lineTo(x, toY(c.low));
      ctx.stroke();

      // Body
      const bodyTop = toY(Math.max(c.open, c.close));
      const bodyBottom = toY(Math.min(c.open, c.close));
      const bodyH = Math.max(bodyBottom - bodyTop, 1);
      ctx.fillStyle = color;
      ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyH);
    });

    // X-axis labels (dates)
    ctx.fillStyle = textColor;
    ctx.textAlign = "center";
    const labelInterval = Math.max(1, Math.floor(maxCandles / 6));
    visibleCandles.forEach((c, i) => {
      if (i % labelInterval === 0) {
        const x = pad.left + i * gap + gap / 2;
        const d = new Date(c.timestamp);
        const label =
          maxCandles > 60
            ? d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" })
            : d.toLocaleDateString("en-IN", {
                day: "2-digit",
                month: "short",
                hour: "2-digit",
                minute: "2-digit",
              });
        ctx.fillText(label, x, height - 8);
      }
    });
  }, [candles]);

  return (
    <div ref={containerRef} className="w-full">
      <canvas ref={canvasRef} className="w-full" />
    </div>
  );
}
