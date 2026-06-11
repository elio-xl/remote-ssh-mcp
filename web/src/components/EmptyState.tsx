import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="mb-3">{icon}</div>
      <h3 className="mb-1.5 text-[15px] font-semibold text-foreground">{title}</h3>
      {description && (
        <p className="mb-4 max-w-sm text-[13px] text-muted-foreground">{description}</p>
      )}
      {action}
    </div>
  );
}
