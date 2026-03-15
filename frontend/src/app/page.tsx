"use client";

import { useEffect, useState } from "react";
import { useOrders, usePositions, useRiskStatus, useStrategies } from "@/hooks/useData";
import { formatCurrency, formatPnl, cn } from "@/lib/utils";

export default function DashboardPage() {
  const [authMsg, setAuthMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Show auth result from Zerodha redirect
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
    <div className="p-8 space-y-8">
      {authMsg && (
        <div
          className={cn(
            "rounded-lg px-4 py-3 flex items-center justify-between text-sm",
            authMsg.type === "success"
              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
              : "bg-red-500/10 text-red-400 border border-red-500/30",
          )}
        >
          <span>{authMsg.type === "success" ? "✓" : "✗"} {authMsg.text}</span>
          <button onClick={() => setAuthMsg(null)} className="text-xs opacity-60 hover:opacity-100">
            Dismiss
          </button>
        </div>
      )}

      <header>
        <h2 className="text-2xl font-bold tracking-tight">Dashboard</h2>
        <p className="text-[var(--muted)] text-sm mt-1">Real-time trading overview</p>
      </header>

      <div className="grid grid-cols-4 gap-4">
        <MetricCard title="Daily P&L" metric="pnl" />
        <MetricCard title="Open Positions" metric="positions" />
        <MetricCard title="Active Strategies" metric="strategies" />
        <MetricCard title="Kill Switch" metric="killswitch" />
      </div>

      <div className="grid grid-cols-2 gap-6">
        <PositionsPanel />
        <OrdersPanel />
      </div>

      <RiskPanel />
    </div>
  );
}

function MetricCard({ title, metric }: { title: string; metric: string }) {
  const { data: risk } = useRiskStatus();
  const { data: positions } = usePositions();
  const { data: strats } = useStrategies();

  let value: React.ReactNode = "—";
  let color = "";

  switch (metric) {
    case "pnl":
      if (risk) {
        value = formatPnl(risk.daily_pnl);
        color = risk.daily_pnl >= 0 ? "text-emerald-400" : "text-red-400";
      }
      break;
    case "positions":
      value = positions?.net?.length?.toString() ?? "0";
      break;
    case "strategies":
      value = strats?.filter((s) => s.state === "running").length.toString() ?? "0";
      break;
    case "killswitch":
      if (risk) {
        value = risk.kill_switch_active ? "ACTIVE" : "OFF";
        color = risk.kill_switch_active ? "text-red-400" : "text-emerald-400";
      }
      break;
  }

  return (
    <div className="card">
      <p className="text-xs text-[var(--muted)] uppercase tracking-wider">{title}</p>
      <p className={cn("text-2xl font-bold mt-2", color)} style={{ fontFamily: "'JetBrains Mono', monospace" }}>
        {value}
      </p>
    </div>
  );
}

function PositionsPanel() {
  const { data, isLoading } = usePositions();

  return (
    <div className="card">
      <h3 className="text-sm font-semibold mb-4">Open Positions</h3>
      {isLoading && <p className="text-[var(--muted)] text-sm">Loading...</p>}
      {data?.net && data.net.length === 0 && (
        <p className="text-[var(--muted)] text-sm">No open positions</p>
      )}
      <div className="space-y-2">
        {data?.net?.map((p) => (
          <div
            key={p.trading_symbol}
            className="flex items-center justify-between py-2 border-b border-[var(--card-border)] last:border-0"
          >
            <div>
              <span className="font-medium text-sm">{p.trading_symbol}</span>
              <span className="text-xs text-[var(--muted)] ml-2">{p.exchange}</span>
            </div>
            <div className="text-right">
              <span className="text-xs text-[var(--muted)] mr-3">
                {p.quantity} @ {p.average_price.toFixed(2)}
              </span>
              <span
                className={cn(
                  "text-sm font-mono font-medium",
                  p.pnl >= 0 ? "pnl-positive" : "pnl-negative",
                )}
              >
                {formatPnl(p.pnl)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OrdersPanel() {
  const { data, isLoading } = useOrders();
  const recentOrders = data?.slice(-10).reverse() ?? [];

  return (
    <div className="card">
      <h3 className="text-sm font-semibold mb-4">Recent Orders</h3>
      {isLoading && <p className="text-[var(--muted)] text-sm">Loading...</p>}
      {recentOrders.length === 0 && !isLoading && (
        <p className="text-[var(--muted)] text-sm">No orders yet</p>
      )}
      <div className="space-y-2">
        {recentOrders.map((o) => (
          <div
            key={o.order_id}
            className="flex items-center justify-between py-2 border-b border-[var(--card-border)] last:border-0"
          >
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "text-xs font-medium px-1.5 py-0.5 rounded",
                  o.transaction_type === "BUY"
                    ? "bg-emerald-500/10 text-emerald-400"
                    : "bg-red-500/10 text-red-400",
                )}
              >
                {o.transaction_type}
              </span>
              <span className="text-sm">{o.trading_symbol}</span>
              <span className="text-xs text-[var(--muted)]">×{o.quantity}</span>
            </div>
            <StatusBadge status={o.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    COMPLETE: "badge-success",
    REJECTED: "badge-danger",
    CANCELLED: "badge-warning",
    PENDING: "badge-info",
    OPEN: "badge-info",
  };

  return <span className={styles[status] || "badge-info"}>{status}</span>;
}

function RiskPanel() {
  const { data } = useRiskStatus();

  if (!data) return null;

  const lossPercent = data.daily_loss_limit > 0
    ? (data.daily_loss / data.daily_loss_limit) * 100
    : 0;

  return (
    <div className="card">
      <h3 className="text-sm font-semibold mb-4">Risk Monitor</h3>
      <div className="grid grid-cols-3 gap-6">
        <div>
          <p className="text-xs text-[var(--muted)]">Daily Loss Used</p>
          <div className="mt-2 h-2 rounded-full bg-white/5 overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                lossPercent > 80 ? "bg-red-500" : lossPercent > 50 ? "bg-amber-500" : "bg-emerald-500",
              )}
              style={{ width: `${Math.min(lossPercent, 100)}%` }}
            />
          </div>
          <p className="text-xs text-[var(--muted)] mt-1">
            {formatCurrency(data.daily_loss)} / {formatCurrency(data.daily_loss_limit)}
          </p>
        </div>
        <div>
          <p className="text-xs text-[var(--muted)]">Order Rate</p>
          <p className="text-lg font-mono font-bold mt-1">
            {data.orders_last_minute}/{data.order_rate_limit}
            <span className="text-xs text-[var(--muted)] ml-1">/min</span>
          </p>
        </div>
        <div>
          <p className="text-xs text-[var(--muted)]">Kill Switch</p>
          <p className={cn("text-lg font-bold mt-1", data.kill_switch_active ? "text-red-400" : "text-emerald-400")}>
            {data.kill_switch_active ? "⚠ ACTIVE" : "✓ OFF"}
          </p>
        </div>
      </div>
    </div>
  );
}
