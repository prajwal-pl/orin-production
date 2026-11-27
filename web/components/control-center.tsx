"use client";

import { useEffect, useMemo, useState } from "react";
import { LoaderCircle } from "lucide-react";
import {
  getBootstrap,
  getBrowserSession,
  logoutBrowser,
  OrinClient,
  pairBrowser,
} from "@/lib/api";
import { useDashboard } from "@/lib/use-dashboard";
import type { BrowserSession, Task } from "@/lib/types";
import { ApprovalsPanel } from "./approvals-panel";
import { Brand } from "./brand";
import { ConnectionsPanel } from "./connections-panel";
import { OverviewPanel } from "./overview-panel";
import { PairScreen } from "./pair-screen";
import { SchedulesPanel } from "./schedules-panel";
import { Shell, type View } from "./shell";
import { SystemPanel } from "./system-panel";
import { MemoryPanel } from "./memory-panel";
import { SkillsPanel } from "./skills-panel";
import { TasksPanel } from "./tasks-panel";
import { Notice } from "./ui";

export function ControlCenter() {
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [booting, setBooting] = useState(true);
  const [pairingAvailable, setPairingAvailable] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const client = useMemo(
    () => (session ? new OrinClient(session.csrf) : null),
    [session],
  );
  const { data, loading, error, unauthorized, lastUpdated, refresh } =
    useDashboard(client);

  useEffect(() => {
    let current = true;
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const desktopPairCode = fragment.get("pair");
    if (desktopPairCode) {
      // A one-time code is delivered through the local desktop webview only.
      window.history.replaceState(null, "", window.location.pathname);
    }
    Promise.allSettled([getBrowserSession(), getBootstrap()]).then(
      async ([sessionResult, bootstrapResult]) => {
        if (!current) return;
        if (sessionResult.status === "fulfilled") {
          setSession(sessionResult.value);
        } else if (desktopPairCode) {
          try {
            const paired = await pairBrowser(desktopPairCode);
            if (current) setSession(paired);
          } catch {
            // Pairing errors remain visible through the manual pairing screen.
          }
        }
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

  async function createTask(request: string) {
    if (!client || !session) return;
    setTaskError(null);
    try {
      const created = await client.post<{ id: string }>("/tasks", {
        session_id: `web:${session.owner}`,
        request,
      });
      setSelectedTaskId(created.id);
      setView("tasks");
      await refresh();
      // Start the run without blocking the composer. The activity view follows
      // the pending task's event stream and refreshes when it changes.
      void client
        .post(`/tasks/${encodeURIComponent(created.id)}/run`)
        .catch((failure) =>
          setTaskError(
            failure instanceof Error
              ? failure.message
              : "Could not start the task",
          ),
        )
        .finally(() => void refresh());
    } catch (failure) {
      setTaskError(
        failure instanceof Error ? failure.message : "Could not start the task",
      );
      await refresh();
    }
  }

  if (booting)
    return (
      <div className="boot-screen">
        <Brand />
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
      {taskError && (
        <Notice kind="error">Task could not start: {taskError}</Notice>
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
          onOpenApprovals={() => setView("approvals")}
          onOpenConnections={() => setView("connections")}
          onOpenSchedules={() => setView("schedules")}
          onCreateTask={createTask}
        />
      )}
      {!loading && view === "tasks" && (
        <TasksPanel
          client={client}
          tasks={data.tasks}
          selectedId={selectedTaskId}
          onSelect={setSelectedTaskId}
          refresh={refresh}
          onCreateTask={createTask}
        />
      )}
      {!loading && view === "connections" && (
        <ConnectionsPanel
          client={client}
          capabilities={data.capabilities}
          grants={data.grants}
          roots={data.roots}
          mcpCalls={data.mcpCalls}
          refresh={refresh}
        />
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
        <SystemPanel
          client={client}
          models={data.models}
          sessions={data.sessions}
          usage={data.usage}
        />
      )}
      {!loading && view === "memory" && (
        <MemoryPanel
          client={client}
          memories={data.memories}
          refresh={refresh}
        />
      )}
      {!loading && view === "skills" && (
        <SkillsPanel
          client={client}
          skills={data.skills}
          metrics={data.skillMetrics}
          refresh={refresh}
        />
      )}
    </Shell>
  );
}
