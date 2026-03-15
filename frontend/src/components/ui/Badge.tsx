/**
 * Badge — inline status indicators.
 */
import { cn } from "@/lib/utils";
import { cva, type VariantProps } from "class-variance-authority";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        success: "bg-emerald-500/10 text-emerald-400",
        danger: "bg-red-500/10 text-red-400",
        warning: "bg-amber-500/10 text-amber-400",
        info: "bg-blue-500/10 text-blue-400",
        neutral: "bg-gray-500/10 text-gray-400",
      },
    },
    defaultVariants: {
      variant: "info",
    },
  },
);

interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

/** Map common order/strategy status strings to badge variants. */
export function StatusBadge({ status }: { status: string }) {
  const variantMap: Record<string, BadgeProps["variant"]> = {
    COMPLETE: "success",
    REJECTED: "danger",
    CANCELLED: "warning",
    PENDING: "info",
    OPEN: "info",
    running: "success",
    paused: "warning",
    stopped: "neutral",
    idle: "neutral",
    error: "danger",
  };
  return (
    <Badge variant={variantMap[status] || "info"}>
      {status.toUpperCase()}
    </Badge>
  );
}

export { badgeVariants };
