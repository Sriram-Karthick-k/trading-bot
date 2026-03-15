/**
 * MetricCard — dashboard summary card with title + formatted value.
 */
import { cn } from "@/lib/utils";
import { Card } from "./Card";

interface MetricCardProps {
  title: string;
  value: React.ReactNode;
  className?: string;
  valueClassName?: string;
  subtitle?: string;
}

export function MetricCard({ title, value, className, valueClassName, subtitle }: MetricCardProps) {
  return (
    <Card className={className}>
      <p className="text-xs text-[var(--muted)] uppercase tracking-wider">{title}</p>
      <p
        className={cn("text-2xl font-bold mt-2", valueClassName)}
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {value}
      </p>
      {subtitle && <p className="text-xs text-[var(--muted)] mt-1">{subtitle}</p>}
    </Card>
  );
}
