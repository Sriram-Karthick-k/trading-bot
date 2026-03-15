/**
 * ProgressBar — horizontal progress indicator.
 */
import { cn } from "@/lib/utils";

interface ProgressBarProps {
  value: number; // 0–1
  className?: string;
  barClassName?: string;
  label?: string;
}

export function ProgressBar({ value, className, barClassName, label }: ProgressBarProps) {
  const pct = Math.min(Math.max(value, 0), 1) * 100;
  return (
    <div className={className}>
      <div className="h-2 rounded-full bg-white/5 overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            pct > 80
              ? "bg-red-500"
              : pct > 50
                ? "bg-amber-500"
                : "bg-emerald-500",
            barClassName,
          )}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
      {label && <p className="text-xs text-[var(--muted)] mt-1">{label}</p>}
    </div>
  );
}
