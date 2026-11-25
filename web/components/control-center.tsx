"use client";

import { useEffect, useMemo, useState } from "react";
import { LoaderCircle, Sparkles } from "lucide-react";
import {
  getBootstrap,
  getBrowserSession,
  logoutBrowser,
  OrinClient,
} from "@/lib/api";
import { useDashboard } from "@/lib/use-dashboard";
import type { BrowserSession, Task } from "@/lib/types";
import { ApprovalsPanel } from "./approvals-panel";
import { ConnectionsPanel } from "./connections-panel";
import { OverviewPanel } from "./overview-panel";
import { PairScreen } from "./pair-screen";
import { SchedulesPanel } from "./schedules-panel";
import { Shell, type View } from "./shell";
import { SystemPanel } from "./system-panel";
import { TasksPanel } from "./tasks-panel";
import { Notice } from "./ui";

export function ControlCenter() {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [booting, setBooting] = useState(true);
  const [pairingAvailable, setPairingAvailable] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const client = useMemo(
    () => (session ? new OrinClient(session.csrf) : null),
    [session],
  );
  const { data, loading, error, unauthorized, lastUpdated, refresh } =
    useDashboard(client);

  useEffect(() => {
    let current = true;
    Promise.allSettled([getBrowserSession(), getBootstrap()]).then(
      ([sessionResult, bootstrapResult]) => {
        if (!current) return;
        if (sessionResult.status === "fulfilled")
          setSession(sessionResult.value);
        if (bootstrapResult.status === "fulfilled")
          setPairingAvailable(bootstrapResult.value.pairing_available);
        setBooting(false);
      },
    );
    return () => {
      current = false;
    };
  }, []);

  useEffect(() => {
    if (unauthorized) {
      setSession(null);
      void getBootstrap()
        .then((state) => setPairingAvailable(state.pairing_available))
        .catch(() => setPairingAvailable(false));
    }
  }, [unauthorized]);

  async function signOut() {
    if (!session) return;
    try {
      await logoutBrowser(session.csrf);
    } finally {
      setSession(null);
      setPairingAvailable(false);
    }
  }

  function openTask(task: Task) {
    setSelectedTaskId(task.id);
    setView("tasks");
  }

  if (booting)
    return (
      <div className="boot-screen">
        <span className="brand-mark">
          <Sparkles size={23} />
        </span>
        <LoaderCircle className="spinning" size={25} />
        <span>Opening Orin…</span>
      </div>
    );
  if (!session || !client)
    return (
      <PairScreen
        available={pairingAvailable}
        onPaired={(paired) => {
          setSession(paired);
          setPairingAvailable(false);
        }}
      />
    );

  return (
    <Shell
      view={view}
      setView={setView}
      owner={session.owner}
      pendingApprovals={
        data.approvals.filter((item) => item.status === "pending").length
      }
      connected={!error}
      lastUpdated={lastUpdated}
      onRefresh={() => void refresh()}
      onLogout={() => void signOut()}
    >
      {error && (
        <Notice kind="error">
          The local service could not refresh this view: {error}. Showing the
          last available data.
        </Notice>
      )}
      {loading && (
        <div className="loading-line">
          <LoaderCircle className="spinning" size={18} /> Loading your
          workspace…
        </div>
      )}
      {!loading && view === "overview" && (
        <OverviewPanel
          data={data}
          onSelectTask={openTask}
          onOpenTasks={() => setView("tasks")}
        />
      )}
      {!loading && view === "tasks" && (
        <TasksPanel
          client={client}
          owner={session.owner}
          tasks={data.tasks}
          selectedId={selectedTaskId}
          onSelect={setSelectedTaskId}
          refresh={refresh}
        />
      )}
      {!loading && view === "connections" && (
        <ConnectionsPanel capabilities={data.capabilities} />
      )}
      {!loading && view === "approvals" && (
        <ApprovalsPanel
          client={client}
          approvals={data.approvals}
          actions={data.actions}
          refresh={refresh}
        />
      )}
      {!loading && view === "schedules" && (
        <SchedulesPanel
          client={client}
          owner={session.owner}
          schedules={data.schedules}
          refresh={refresh}
        />
      )}
      {!loading && view === "system" && (
        <SystemPanel models={data.models} sessions={data.sessions} />
      )}
    </Shell>
  );
}
