"use client";

import { useState, useEffect } from "react";
import { useRiskLimits, useRiskStatus, useTradingMode, useTradingModeStatus, usePaperSettings } from "@/hooks/useData";
import { config as configApi } from "@/lib/api";
import { cn, formatCurrency } from "@/lib/utils";
import type { TradingMode } from "@/types";

export default function SettingsPage() {
  return (
    <div className="p-8 space-y-8">
      <header>
        <h2 className="text-2xl font-bold tracking-tight">Settings</h2>
        <p className="text-[var(--muted)] text-sm mt-1">Configure risk limits and system settings</p>
      </header>

      <TradingModePanel />
      <PaperSettingsPanel />
      <KillSwitchPanel />
      <RiskLimitsPanel />
    </div>
  );
}

function TradingModePanel() {
  const { data: modeData, mutate: mutateMode } = useTradingMode();
  const { data: statusData, mutate: mutateStatus } = useTradingModeStatus();
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentMode = modeData?.mode ?? "live";
  const isPaper = currentMode === "paper";

  const handleSwitch = async (mode: TradingMode) => {
    if (mode === currentMode) return;
    setSwitching(true);
    setError(null);
    try {
      await configApi.setTradingMode(mode);
      mutateMode();
      mutateStatus();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to switch mode";
      setError(msg);
    } finally {
      setSwitching(false);
    }
  };

  const handleReset = async () => {
    if (!isPaper) return;
    try {
      await configApi.resetPaperTrading();
      mutateStatus();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to reset";
      setError(msg);
    }
  };

  const paperStatus = statusData?.paper_status;

  return (
    <div className={cn(
      "card border-2 transition-colors",
      isPaper ? "border-amber-500/40" : "border-[var(--card-border)]"
    )}>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h3 className="font-semibold text-lg flex items-center gap-2.5">
            Trading Mode
            <span className={cn(
              "text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full",
              isPaper
                ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                : "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
            )}>
              {currentMode}
            </span>
          </h3>
          <p className="text-sm text-[var(--muted)] mt-1">
            {isPaper
              ? "Paper mode — real market data, simulated fills. No real money at risk."
              : "Live mode — real orders placed through Zerodha. Real money at risk."}
          </p>
        </div>
      </div>

      {/* Mode selector */}
      <div className="flex gap-3 mb-5">
        <button
          className={cn(
            "flex-1 rounded-lg px-4 py-3 border-2 text-sm font-semibold transition-all",
            !isPaper
              ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
              : "border-[var(--card-border)] bg-transparent text-[var(--muted)] hover:border-[var(--muted)] hover:text-white"
          )}
          onClick={() => handleSwitch("live")}
          disabled={switching || !isPaper}
        >
          <div className="text-left">
            <div className="flex items-center gap-2">
              <span className={cn("w-2 h-2 rounded-full", !isPaper ? "bg-emerald-400" : "bg-[var(--muted)]")} />
              Live Trading
            </div>
            <p className="text-xs opacity-60 mt-1 font-normal">Real orders on Zerodha</p>
          </div>
        </button>
        <button
          className={cn(
            "flex-1 rounded-lg px-4 py-3 border-2 text-sm font-semibold transition-all",
            isPaper
              ? "border-amber-500/50 bg-amber-500/10 text-amber-400"
              : "border-[var(--card-border)] bg-transparent text-[var(--muted)] hover:border-[var(--muted)] hover:text-white"
          )}
          onClick={() => handleSwitch("paper")}
          disabled={switching || isPaper}
        >
          <div className="text-left">
            <div className="flex items-center gap-2">
              <span className={cn("w-2 h-2 rounded-full", isPaper ? "bg-amber-400" : "bg-[var(--muted)]")} />
              Paper Trading
            </div>
            <p className="text-xs opacity-60 mt-1 font-normal">Simulated fills, no real money</p>
          </div>
        </button>
      </div>

      {/* Error message */}
      {error && (
        <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mb-4">
          {error}
        </div>
      )}

      {/* Paper trading status (only shown in paper mode) */}
      {isPaper && paperStatus && (
        <div className="border-t border-[var(--card-border)] pt-4">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-semibold text-[var(--muted)] uppercase tracking-wider">
              Paper Session
            </h4>
            <button
              className="text-xs text-[var(--muted)] hover:text-white border border-[var(--card-border)] rounded px-2.5 py-1 transition-colors"
              onClick={handleReset}
            >
              Reset Session
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-[var(--background)] rounded-lg p-3">
              <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Capital</p>
              <p className="text-sm font-bold mt-0.5 font-mono">
                {formatCurrency(paperStatus.available_capital)}
              </p>
            </div>
            <div className="bg-[var(--background)] rounded-lg p-3">
              <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Realised P&L</p>
              <p className={cn(
                "text-sm font-bold mt-0.5 font-mono",
                paperStatus.realised_pnl >= 0 ? "pnl-positive" : "pnl-negative"
              )}>
                {paperStatus.realised_pnl >= 0 ? "+" : ""}{formatCurrency(paperStatus.realised_pnl)}
              </p>
            </div>
            <div className="bg-[var(--background)] rounded-lg p-3">
              <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Fills</p>
              <p className="text-sm font-bold mt-0.5 font-mono">{paperStatus.total_fills}</p>
            </div>
            <div className="bg-[var(--background)] rounded-lg p-3">
              <p className="text-[10px] text-[var(--muted)] uppercase tracking-wider">Open Pos</p>
              <p className="text-sm font-bold mt-0.5 font-mono">{paperStatus.open_positions}</p>
            </div>
          </div>
        </div>
      )}

      {switching && (
        <p className="text-xs text-[var(--muted)] mt-3">Switching mode...</p>
      )}
    </div>
  );
}

function PaperSettingsPanel() {
  const { data: modeData } = useTradingMode();
  const { data: settings, mutate } = usePaperSettings();
  const [form, setForm] = useState({
    initial_capital: 1000000,
    slippage_pct: 0.05,
    brokerage_per_order: 20,
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isPaper = modeData?.mode === "paper";

  useEffect(() => {
    if (settings) {
      setForm({
        initial_capital: settings.initial_capital,
        slippage_pct: settings.slippage_pct,
        brokerage_per_order: settings.brokerage_per_order,
      });
    }
  }, [settings]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await configApi.updatePaperSettings(form);
      mutate();
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to save";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h3 className="font-semibold text-lg">Paper Trading Settings</h3>
          <p className="text-sm text-[var(--muted)] mt-1">
            Configure simulated capital, slippage, and brokerage for paper trading.
            {isPaper && " Changes apply after next mode switch or restart."}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div>
          <label className="text-xs text-[var(--muted)] block mb-1">Initial Capital</label>
          <input
            className="input w-full"
            type="number"
            min={1000}
            step={10000}
            value={form.initial_capital}
            onChange={(e) => setForm({ ...form, initial_capital: Number(e.target.value) })}
          />
        </div>
        <div>
          <label className="text-xs text-[var(--muted)] block mb-1">Slippage %</label>
          <input
            className="input w-full"
            type="number"
            min={0}
            max={5}
            step={0.01}
            value={form.slippage_pct}
            onChange={(e) => setForm({ ...form, slippage_pct: Number(e.target.value) })}
          />
        </div>
        <div>
          <label className="text-xs text-[var(--muted)] block mb-1">Brokerage/Order</label>
          <input
            className="input w-full"
            type="number"
            min={0}
            step={5}
            value={form.brokerage_per_order}
            onChange={(e) => setForm({ ...form, brokerage_per_order: Number(e.target.value) })}
          />
        </div>
      </div>

      {error && (
        <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mt-4">
          {error}
        </div>
      )}

      <div className="mt-5 flex items-center gap-3">
        <button className="btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save Paper Settings"}
        </button>
        {saved && <span className="text-sm text-emerald-400">Saved</span>}
      </div>
    </div>
  );
}

function KillSwitchPanel() {
  const { data: status, mutate } = useRiskStatus();

  if (!status) return null;

  return (
    <div className={cn("card border-2", status.kill_switch_active ? "border-red-500/50" : "border-[var(--card-border)]")}>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-lg">Kill Switch</h3>
          <p className="text-sm text-[var(--muted)]">
            Emergency stop for all trading activity
          </p>
        </div>
        {status.kill_switch_active ? (
          <button
            className="bg-emerald-600 hover:bg-emerald-700 text-white px-6 py-3 rounded-lg font-bold transition-colors"
            onClick={async () => { await configApi.deactivateKillSwitch(); mutate(); }}
          >
            ✓ Deactivate
          </button>
        ) : (
          <button
            className="bg-red-600 hover:bg-red-700 text-white px-6 py-3 rounded-lg font-bold transition-colors"
            onClick={async () => { await configApi.activateKillSwitch(); mutate(); }}
          >
            ⚠ Activate Kill Switch
          </button>
        )}
      </div>
    </div>
  );
}

function RiskLimitsPanel() {
  const { data: limits, mutate } = useRiskLimits();
  const [form, setForm] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (limits) {
      setForm({
        max_order_value: limits.max_order_value,
        max_position_value: limits.max_position_value,
        max_loss_per_trade: limits.max_loss_per_trade,
        max_daily_loss: limits.max_daily_loss,
        max_open_orders: limits.max_open_orders,
        max_open_positions: limits.max_open_positions,
        max_quantity_per_order: limits.max_quantity_per_order,
        max_orders_per_minute: limits.max_orders_per_minute,
      });
    }
  }, [limits]);

  const handleSave = async () => {
    setSaving(true);
    await configApi.updateRiskLimits(form);
    mutate();
    setSaving(false);
  };

  const fields = [
    { key: "max_order_value", label: "Max Order Value (₹)", type: "currency" },
    { key: "max_position_value", label: "Max Position Value (₹)", type: "currency" },
    { key: "max_loss_per_trade", label: "Max Loss Per Trade (₹)", type: "currency" },
    { key: "max_daily_loss", label: "Max Daily Loss (₹)", type: "currency" },
    { key: "max_open_orders", label: "Max Open Orders", type: "number" },
    { key: "max_open_positions", label: "Max Open Positions", type: "number" },
    { key: "max_quantity_per_order", label: "Max Qty Per Order", type: "number" },
    { key: "max_orders_per_minute", label: "Max Orders/Minute", type: "number" },
  ];

  return (
    <div className="card">
      <h3 className="font-semibold text-lg mb-6">Risk Limits</h3>
      <div className="grid grid-cols-2 gap-4">
        {fields.map((f) => (
          <div key={f.key}>
            <label className="text-xs text-[var(--muted)] block mb-1">{f.label}</label>
            <input
              className="input w-full"
              type="number"
              value={form[f.key] ?? ""}
              onChange={(e) => setForm({ ...form, [f.key]: Number(e.target.value) })}
            />
          </div>
        ))}
      </div>
      <div className="mt-6">
        <button className="btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save Risk Limits"}
        </button>
      </div>
    </div>
  );
}
