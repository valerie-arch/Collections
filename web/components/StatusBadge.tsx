import clsx from "clsx";

const tone: Record<string, string> = {
  succeeded: "badge-success",
  running: "badge-warning",
  queued: "badge-muted",
  pending: "badge-muted",
  failed: "badge-danger",
  open: "badge-warning",
  resolved: "badge-success",
  escalated: "badge-danger",
  cleared: "badge-success",
  critical: "badge-danger",
  error: "badge-danger",
  warning: "badge-warning",
  info: "badge-muted",
};

export function StatusBadge({ value }: { value: string }) {
  const cls = tone[value] ?? "badge-muted";
  return <span className={clsx(cls)}>{value}</span>;
}
