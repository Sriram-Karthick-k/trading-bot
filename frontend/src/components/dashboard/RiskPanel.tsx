/**
 * RiskPanel — dashboard panel showing risk metrics.
 */
"use client";

import { useRiskStatus } from "@/hooks/useData";
import { cn, formatCurrency } from "@/lib/utils";
import { Card, CardTitle } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/ProgressBar";

export function RiskPanel() {
  const { data } = useRiskStatus();

  if (!data) return null;

  const lossPercent =
    data.daily_loss_limit > 0
      ? (data.daily_loss / data.daily_loss_limit) * 100
      : 0;

  return (
    <Card>
      <CardTitle>Risk Monitor</CardTitle>
      <div className="grid grid-cols-3 gap-6 mt-4">
        <div>
          <p className="text-xs text-[var(--muted)]">Daily Loss Used</p>
          <ProgressBar
            value={lossPercent / 100}
            className="mt-2"
            label={`${formatCurrency(data.daily_loss)} / ${formatCurrency(data.daily_loss_limit)}`}
          />
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
          <p
            className={cn(
              "text-lg font-bold mt-1",
              data.kill_switch_active ? "text-red-400" : "text-emerald-400",
            )}
          >
            {data.kill_switch_active ? "⚠ ACTIVE" : "✓ OFF"}
          </p>
        </div>
      </div>
    </Card>
  );
}
