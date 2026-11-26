"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, OrinClient } from "./api";
import type {
  Action,
  AccessGrant,
  Approval,
  Capability,
  DashboardData,
  FilesystemRoot,
  ModelHealth,
  MemoryRecord,
  SkillVersion,
  SkillMetric,
  UsageSummary,
  Schedule,
  Session,
  Task,
} from "./types";

const empty: DashboardData = {
  tasks: [],
  sessions: [],
  models: [],
  capabilities: [],
  grants: [],
  roots: [],
  approvals: [],
  actions: [],
  schedules: [],
  memories: [],
  skills: [],
  skillMetrics: [],
  usage: [],
};

export function useDashboard(client: OrinClient | null) {
  const [data, setData] = useState<DashboardData>(empty);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    if (!client) return;
    try {
      const [
        tasks,
        sessions,
        models,
        capabilities,
        grants,
        roots,
        approvals,
        actions,
        schedules,
        memories,
        skills,
        skillMetrics,
        usage,
      ] = await Promise.all([
        client.get<Task[]>("/tasks"),
        client.get<Session[]>("/sessions"),
        client.get<ModelHealth[]>("/models"),
        client.get<Capability[]>("/capabilities"),
        client.get<AccessGrant[]>("/policy/grants"),
        client.get<FilesystemRoot[]>("/policy/roots"),
        client.get<Approval[]>("/approvals"),
        client.get<Action[]>("/actions"),
        client.get<Schedule[]>("/schedules"),
        client.get<MemoryRecord[]>("/memories"),
        client.get<SkillVersion[]>("/skills"),
        client.get<SkillMetric[]>("/skills/metrics"),
        client.get<UsageSummary[]>("/usage"),
      ]);
      setData({
        tasks,
        sessions,
        models,
        capabilities,
        grants,
        roots,
        approvals,
        actions,
        schedules,
        memories,
        skills,
        skillMetrics,
        usage,
      });
      setError(null);
      setUnauthorized(false);
      setLastUpdated(new Date());
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401)
        setUnauthorized(true);
      setError(
        failure instanceof Error
          ? failure.message
          : "Could not reach the local runtime",
      );
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    if (!client) return;
    void refresh();
    const interval = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(interval);
  }, [client, refresh]);

  return { data, loading, error, unauthorized, lastUpdated, refresh };
}

export function useTaskEvents(
  taskId: string | null,
  active: boolean,
  onEvent: () => void,
) {
  const [state, setState] = useState<"idle" | "live" | "reconnecting">("idle");

  useEffect(() => {
    if (!taskId || !active) {
      setState("idle");
      return;
    }
    let closed = false;
    let cursor = 0;
    let connection: EventSource | null = null;
    let retry: number | null = null;
    const connect = () => {
      if (closed) return;
      connection = new EventSource(
        `/tasks/${encodeURIComponent(taskId)}/events?after=${cursor}`,
      );
      connection.onopen = () => setState("live");
      const receive = (event: Event) => {
        const message = event as MessageEvent;
        const parsed = Number(message.lastEventId);
        if (Number.isFinite(parsed) && parsed > cursor) cursor = parsed;
        onEvent();
      };
      for (const name of [
        "created",
        "running",
        "step",
        "paused",
        "completed",
        "cancelled",
      ]) {
        connection.addEventListener(name, receive);
      }
      connection.onerror = () => {
        connection?.close();
        setState("reconnecting");
        if (!closed) retry = window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      connection?.close();
      if (retry !== null) window.clearTimeout(retry);
    };
  }, [taskId, active, onEvent]);

  return state;
}
