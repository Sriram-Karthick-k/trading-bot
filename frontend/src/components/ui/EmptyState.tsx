/**
 * EmptyState — empty placeholder for pages with no data.
 */
interface EmptyStateProps {
  icon?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon = "∅", title, description, action }: EmptyStateProps) {
  return (
    <div className="card text-center py-16">
      <p className="text-4xl mb-4">{icon}</p>
      <p className="text-[var(--muted)]">{title}</p>
      {description && (
        <p className="text-xs text-[var(--muted)] mt-1">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
