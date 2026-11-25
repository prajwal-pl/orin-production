"use client";

import { useEffect } from "react";
import {
  CalendarDays,
  Command,
  LayoutGrid,
  ListChecks,
  LogOut,
  Plug2,
  RefreshCw,
  Settings2,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { formatDate } from "@/lib/format";
import { Brand } from "./brand";
import { ThemeToggle } from "./theme-toggle";

export type View =
  "overview" | "tasks" | "connections" | "approvals" | "schedules" | "system";

const navigation: {
  id: View;
  label: string;
  icon: LucideIcon;
  group: "workspace" | "manage";
}[] = [
  { id: "overview", label: "Workbench", icon: LayoutGrid, group: "workspace" },
  { id: "tasks", label: "Activity", icon: ListChecks, group: "workspace" },
  {
    id: "approvals",
    label: "Approvals",
    icon: ShieldCheck,
    group: "workspace",
  },
  {
    id: "schedules",
    label: "Automations",
    icon: CalendarDays,
    group: "manage",
  },
  { id: "connections", label: "Connections", icon: Plug2, group: "manage" },
  { id: "system", label: "System", icon: Settings2, group: "manage" },
];

const descriptions: Record<View, string> = {
  overview: "Your next task, recent work, and decisions in one place.",
  tasks: "Follow work from request to result.",
  approvals: "Review the exact action before Orin proceeds.",
  schedules: "Make recurring work predictable.",
  connections: "See which services this runtime can read.",
  system: "Observed model health and local sessions.",
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
  const active = navigation.find((item) => item.id === view)!;

  useEffect(() => {
    document.title = `${active.label} · Orin`;
  }, [active.label]);

  const links = (group: "workspace" | "manage") =>
    navigation
      .filter((item) => item.group === group)
      .map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          className={`nav-item ${view === id ? "active" : ""}`}
          aria-current={view === id ? "page" : undefined}
          onClick={() => setView(id)}
        >
          <Icon size={18} strokeWidth={1.8} />
          <span>{label}</span>
          {id === "approvals" && pendingApprovals > 0 && (
            <span className="nav-count">{pendingApprovals}</span>
          )}
        </button>
      ));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-head">
          <Brand />
          <span className="sidebar-edition">PERSONAL AGENT</span>
        </div>
        <div className="workspace-switch">
          <span className="workspace-avatar">
            {owner.slice(0, 1).toUpperCase()}
          </span>
          <span>
            <strong>{owner}&apos;s workspace</strong>
            <small>Local control center</small>
          </span>
        </div>
        <nav className="sidebar-nav" aria-label="Primary navigation">
          <div className="nav-group">
            <p>WORKSPACE</p>
            {links("workspace")}
          </div>
          <div className="nav-group">
            <p>MANAGE</p>
            {links("manage")}
          </div>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-runtime">
            <span
              className={`runtime-indicator ${connected ? "" : "offline"}`}
            />
            <span>
              <strong>
                {connected ? "Runtime online" : "Runtime unavailable"}
              </strong>
              <small>Running on this computer</small>
            </span>
          </div>
          <button type="button" className="sidebar-logout" onClick={onLogout}>
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="topbar-heading">
            <p className="breadcrumb">
              <Command size={13} /> ORIN <span>/</span>{" "}
              {active.label.toUpperCase()}
            </p>
            <h1>{active.label}</h1>
            <p>{descriptions[view]}</p>
          </div>
          <div className="topbar-actions">
            <span className={`connection-pill ${connected ? "" : "offline"}`}>
              <span className="runtime-indicator" />{" "}
              {connected ? "Local and ready" : "Connection lost"}
            </span>
            <button
              className="icon-button"
              type="button"
              title="Refresh"
              aria-label="Refresh dashboard"
              onClick={onRefresh}
            >
              <RefreshCw size={17} />
            </button>
            <ThemeToggle />
            <span className="header-avatar" title={`Signed in as ${owner}`}>
              {owner.slice(0, 1).toUpperCase()}
            </span>
          </div>
        </header>
        <main className="content-area" key={view}>
          {children}
        </main>
        <footer className="app-footer">
          <span>
            <span className="footer-mark" /> PRIVATE LOCAL RUNTIME
          </span>
          <span>Updated {formatDate(lastUpdated?.toISOString())}</span>
        </footer>
      </div>
    </div>
  );
}
