"use client";

import {
  Activity,
  CalendarClock,
  CheckCheck,
  CircleDot,
  DatabaseZap,
  LayoutDashboard,
  LogOut,
  RefreshCw,
  Settings2,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { formatDate } from "@/lib/format";

export type View =
  "overview" | "tasks" | "connections" | "approvals" | "schedules" | "system";

const navigation: { id: View; label: string; icon: LucideIcon }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "tasks", label: "Tasks", icon: Activity },
  { id: "connections", label: "Connections", icon: DatabaseZap },
  { id: "approvals", label: "Approvals", icon: CheckCheck },
  { id: "schedules", label: "Schedules", icon: CalendarClock },
  { id: "system", label: "System", icon: Settings2 },
];

const descriptions: Record<View, string> = {
  overview: "A clear picture of your local agent.",
  tasks: "Follow the work Orin is doing.",
  connections: "See what Orin can access on this device.",
  approvals: "Review exact actions before they run.",
  schedules: "Keep recurring work on your terms.",
  system: "Models, sessions, and runtime health.",
};

export function Shell({
  view,
  setView,
  owner,
  pendingApprovals,
  connected,
  lastUpdated,
  onRefresh,
  onLogout,
  children,
}: {
  view: View;
  setView: (view: View) => void;
  owner: string;
  pendingApprovals: number;
  connected: boolean;
  lastUpdated: Date | null;
  onRefresh: () => void;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">
            <Sparkles size={20} />
          </span>
          <span>
            orin<span className="brand-period">.</span>
          </span>
        </div>
        <div className="sidebar-caption">CONTROL CENTER</div>
        <nav className="sidebar-nav" aria-label="Primary navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`nav-item ${view === id ? "active" : ""}`}
              aria-current={view === id ? "page" : undefined}
              onClick={() => setView(id)}
            >
              <Icon size={18} strokeWidth={1.9} />
              <span>{label}</span>
              {id === "approvals" && pendingApprovals > 0 && (
                <span className="nav-count">{pendingApprovals}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-card">
            <span className="local-card-icon">
              <CircleDot size={17} />
            </span>
            <div>
              <strong>Local runtime</strong>
              <span>Private to this device</span>
            </div>
          </div>
          <button type="button" className="sidebar-logout" onClick={onLogout}>
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div>
            <p className="eyebrow">WORKSPACE / {view.toUpperCase()}</p>
            <h1>{navigation.find((item) => item.id === view)?.label}</h1>
            <p className="topbar-description">{descriptions[view]}</p>
          </div>
          <div className="topbar-actions">
            <div className={`connection-pill ${connected ? "" : "offline"}`}>
              <span className="status-dot" />
              {connected ? "Local service online" : "Connection lost"}
            </div>
            <button
              className="icon-button"
              type="button"
              title="Refresh"
              aria-label="Refresh dashboard"
              onClick={onRefresh}
            >
              <RefreshCw size={18} />
            </button>
            <div className="owner-avatar" title={`Signed in as ${owner}`}>
              {owner.slice(0, 1).toUpperCase()}
            </div>
          </div>
        </header>
        <main className="content-area">{children}</main>
        <footer className="app-footer">
          <span>Orin runs on this computer</span>
          <span>Last updated {formatDate(lastUpdated?.toISOString())}</span>
        </footer>
      </div>
    </div>
  );
}
