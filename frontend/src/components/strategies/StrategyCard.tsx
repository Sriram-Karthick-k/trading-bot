/**
 * StrategyCard — displays a single strategy with controls.
 */
"use client";

import { strategies as strategiesApi } from "@/lib/api";
import { cn, formatPnl } from "@/lib/utils";
import type { StrategySnapshot } from "@/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/Badge";

interface StrategyCardProps {
  strategy: StrategySnapshot;
  onAction: () => void;
}

export function StrategyCard({ strategy: s, onAction }: StrategyCardProps) {
  return (
    <Card className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold">{s.name}</h3>
          <p className="text-xs text-[var(--muted)] font-mono">{s.strategy_id}</p>
        </div>
        <StatusBadge status={s.state} />
      </div>

      <div className="grid grid-cols-4 gap-4 text-center">
        <div>
          <p className="text-xs text-[var(--muted)]">Signals</p>
          <p className="font-mono font-bold">{s.metrics.total_signals}</p>
        </div>
        <div>
          <p className="text-xs text-[var(--muted)]">Trades</p>
          <p className="font-mono font-bold">{s.metrics.total_trades}</p>
        </div>
        <div>
          <p className="text-xs text-[var(--muted)]">Win Rate</p>
          <p className="font-mono font-bold">
            {s.metrics.total_trades > 0
              ? `${((s.metrics.winning_trades / s.metrics.total_trades) * 100).toFixed(0)}%`
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-[var(--muted)]">P&L</p>
          <p
            className={cn(
              "font-mono font-bold",
              s.metrics.total_pnl >= 0 ? "pnl-positive" : "pnl-negative",
            )}
          >
            {formatPnl(s.metrics.total_pnl)}
          </p>
        </div>
      </div>

      <div className="flex gap-2">
        {(s.state === "idle" || s.state === "stopped") && (
          <Button
            size="sm"
            onClick={async () => { await strategiesApi.start(s.strategy_id); onAction(); }}
          >
            Start
          </Button>
        )}
        {s.state === "running" && (
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => { await strategiesApi.pause(s.strategy_id); onAction(); }}
            >
              Pause
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={async () => { await strategiesApi.stop(s.strategy_id); onAction(); }}
            >
              Stop
            </Button>
          </>
        )}
        {s.state === "paused" && (
          <>
            <Button
              size="sm"
              onClick={async () => { await strategiesApi.resume(s.strategy_id); onAction(); }}
            >
              Resume
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={async () => { await strategiesApi.stop(s.strategy_id); onAction(); }}
            >
              Stop
            </Button>
          </>
        )}
      </div>
    </Card>
  );
}
