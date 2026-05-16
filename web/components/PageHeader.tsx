export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6 mb-8">
      <div>
        {eyebrow && (
          <div className="text-xs font-medium uppercase tracking-wider text-accent-600 mb-2">
            {eyebrow}
          </div>
        )}
        <h1 className="text-3xl font-display tracking-tightest text-ink leading-tight">
          {title}
        </h1>
        {description && (
          <p className="mt-2 text-ink-muted max-w-2xl">{description}</p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
