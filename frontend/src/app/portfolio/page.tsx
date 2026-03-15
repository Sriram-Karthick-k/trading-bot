"use client";

import { usePositions, useHoldings, useMargins } from "@/hooks/useData";
import { cn, formatCurrency, formatPnl, formatPercent } from "@/lib/utils";

export default function PortfolioPage() {
  return (
    <div className="p-8 space-y-8">
      <header>
        <h2 className="text-2xl font-bold tracking-tight">Portfolio</h2>
        <p className="text-[var(--muted)] text-sm mt-1">Positions, holdings & margins</p>
      </header>

      <MarginsOverview />

      <div className="grid grid-cols-1 gap-6">
        <PositionsTable />
        <HoldingsTable />
      </div>
    </div>
  );
}

function MarginsOverview() {
  const { data } = useMargins();

  if (!data) return null;

  return (
    <div className="grid grid-cols-3 gap-4">
      {data.equity && (
        <>
          <div className="card">
            <p className="text-xs text-[var(--muted)] uppercase">Available Cash</p>
            <p className="text-xl font-bold mt-1 font-mono">{formatCurrency(data.equity.available_cash)}</p>
          </div>
          <div className="card">
            <p className="text-xs text-[var(--muted)] uppercase">Used Margin</p>
            <p className="text-xl font-bold mt-1 font-mono">{formatCurrency(data.equity.used_margin)}</p>
          </div>
          <div className="card">
            <p className="text-xs text-[var(--muted)] uppercase">Available Margin</p>
            <p className="text-xl font-bold mt-1 font-mono text-emerald-400">
              {formatCurrency(data.equity.available_margin)}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function PositionsTable() {
  const { data, isLoading } = usePositions();
  const totalPnl = data?.net?.reduce((sum, p) => sum + p.pnl, 0) ?? 0;

  return (
    <div className="card overflow-hidden p-0">
      <div className="p-4 border-b border-[var(--card-border)] flex items-center justify-between">
        <h3 className="font-semibold text-sm">Positions</h3>
        <span className={cn("text-sm font-mono font-bold", totalPnl >= 0 ? "pnl-positive" : "pnl-negative")}>
          Total: {formatPnl(totalPnl)}
        </span>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--card-border)] bg-white/[0.02]">
            <th className="text-left p-3 text-xs text-[var(--muted)] font-medium">Symbol</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">Qty</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">Avg Price</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">LTP</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">P&L</th>
          </tr>
        </thead>
        <tbody>
          {isLoading && (
            <tr><td colSpan={5} className="p-6 text-center text-[var(--muted)]">Loading...</td></tr>
          )}
          {data?.net?.length === 0 && (
            <tr><td colSpan={5} className="p-6 text-center text-[var(--muted)]">No positions</td></tr>
          )}
          {data?.net?.map((p) => (
            <tr key={`${p.exchange}-${p.trading_symbol}`} className="border-b border-[var(--card-border)] hover:bg-white/[0.02]">
              <td className="p-3">
                <span className="font-medium">{p.trading_symbol}</span>
                <span className="text-xs text-[var(--muted)] ml-1">{p.exchange} · {p.product}</span>
              </td>
              <td className={cn("p-3 text-right font-mono", p.quantity < 0 ? "text-red-400" : "")}>
                {p.quantity}
              </td>
              <td className="p-3 text-right font-mono">{p.average_price.toFixed(2)}</td>
              <td className="p-3 text-right font-mono">{p.last_price.toFixed(2)}</td>
              <td className={cn("p-3 text-right font-mono font-medium", p.pnl >= 0 ? "pnl-positive" : "pnl-negative")}>
                {formatPnl(p.pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HoldingsTable() {
  const { data, isLoading } = useHoldings();

  return (
    <div className="card overflow-hidden p-0">
      <div className="p-4 border-b border-[var(--card-border)]">
        <h3 className="font-semibold text-sm">Holdings</h3>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--card-border)] bg-white/[0.02]">
            <th className="text-left p-3 text-xs text-[var(--muted)] font-medium">Symbol</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">Qty</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">Avg Price</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">LTP</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">P&L</th>
            <th className="text-right p-3 text-xs text-[var(--muted)] font-medium">Day Change</th>
          </tr>
        </thead>
        <tbody>
          {isLoading && (
            <tr><td colSpan={6} className="p-6 text-center text-[var(--muted)]">Loading...</td></tr>
          )}
          {data?.length === 0 && (
            <tr><td colSpan={6} className="p-6 text-center text-[var(--muted)]">No holdings</td></tr>
          )}
          {data?.map((h) => (
            <tr key={`${h.exchange}-${h.trading_symbol}`} className="border-b border-[var(--card-border)] hover:bg-white/[0.02]">
              <td className="p-3">
                <span className="font-medium">{h.trading_symbol}</span>
                <span className="text-xs text-[var(--muted)] ml-1">{h.exchange}</span>
              </td>
              <td className="p-3 text-right font-mono">{h.quantity}</td>
              <td className="p-3 text-right font-mono">{h.average_price.toFixed(2)}</td>
              <td className="p-3 text-right font-mono">{h.last_price.toFixed(2)}</td>
              <td className={cn("p-3 text-right font-mono font-medium", h.pnl >= 0 ? "pnl-positive" : "pnl-negative")}>
                {formatPnl(h.pnl)}
              </td>
              <td className={cn("p-3 text-right font-mono", (h.day_change_percentage ?? 0) >= 0 ? "pnl-positive" : "pnl-negative")}>
                {formatPercent(h.day_change_percentage ?? 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
