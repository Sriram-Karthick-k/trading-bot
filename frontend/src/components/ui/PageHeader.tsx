/**
 * PageHeader — consistent page header with title + subtitle + optional action.
 */
interface PageHeaderProps {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export function PageHeader({ title, subtitle, action }: PageHeaderProps) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
        {subtitle && (
          <p className="text-[var(--muted)] text-sm mt-1">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}
