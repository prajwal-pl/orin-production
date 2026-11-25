import { CircleHelp, type LucideIcon } from "lucide-react";
import { titleCase } from "@/lib/format";

export function StatusBadge({ status }: { status: string }) {
  const tone = ["completed", "approved", "active", "configured"].includes(
    status,
  )
    ? "success"
    : status === "running"
      ? "info"
      : ["paused", "pending", "unknown", "prepared", "executing"].includes(
            status,
          )
        ? "warning"
        : ["failed", "denied", "unavailable", "expired"].includes(status)
          ? "danger"
          : "neutral";
  return (
    <span className={`status-badge status-${tone}`}>
      <span className="status-dot" />
      {titleCase(status)}
    </span>
  );
}

export function EmptyState({
  icon: Icon = CircleHelp,
  title,
  description,
}: {
  icon?: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <Icon size={25} strokeWidth={1.7} />
      <strong>{title}</strong>
      <p>{description}</p>
    </div>
  );
}

export function SectionHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="section-action">{action}</div>}
    </div>
  );
}

export function Notice({
  kind = "info",
  children,
}: {
  kind?: "info" | "error" | "success";
  children: React.ReactNode;
}) {
  return (
    <div
      className={`notice notice-${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
