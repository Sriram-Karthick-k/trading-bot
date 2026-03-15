"use client";

import { useState, useEffect } from "react";
import { useRiskLimits, useRiskStatus } from "@/hooks/useData";
import { config as configApi } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function SettingsPage() {
  return (
    <div className="p-8 space-y-8">
      <header>
        <h2 className="text-2xl font-bold tracking-tight">Settings</h2>
        <p className="text-[var(--muted)] text-sm mt-1">Configure risk limits and system settings</p>
      </header>

      <KillSwitchPanel />
      <RiskLimitsPanel />
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
