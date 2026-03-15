/**
 * ProviderCard — displays a single broker provider with actions.
 */
"use client";

import { providers as providersApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ProviderInfo } from "@/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

interface ProviderCardProps {
  provider: ProviderInfo;
  onAction: () => void;
}

export function ProviderCard({ provider: p, onAction }: ProviderCardProps) {
  return (
    <Card
      className={cn(
        "border-2 transition-colors",
        p.is_active ? "border-brand-500/50" : "border-[var(--card-border)]",
      )}
    >
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold">{p.display_name}</h3>
          <p className="text-xs text-[var(--muted)] font-mono">{p.name}</p>
        </div>
        {p.is_active && <Badge variant="success">ACTIVE</Badge>}
      </div>

      <div className="space-y-2 text-xs text-[var(--muted)]">
        <p>Exchanges: {p.supported_exchanges.join(", ")}</p>
      </div>

      <div className="mt-4 flex gap-2">
        {!p.is_active && (
          <Button
            size="sm"
            onClick={async () => { await providersApi.activate(p.name); onAction(); }}
          >
            Activate
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={async () => {
            const health = await providersApi.health(p.name);
            alert(
              `${p.display_name}: ${health.healthy ? "Healthy" : "Unhealthy"} (${health.latency_ms}ms)`,
            );
          }}
        >
          Health Check
        </Button>
      </div>
    </Card>
  );
}
