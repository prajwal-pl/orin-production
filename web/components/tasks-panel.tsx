"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Ban,
  CirclePlay,
  Clock3,
  Search,
  Send,
  TerminalSquare,
} from "lucide-react";
import { OrinClient } from "@/lib/api";
import { formatDate, formatNumber, shortId, titleCase } from "@/lib/format";
import { useTaskEvents } from "@/lib/use-dashboard";
import type { Task, UsageRecord } from "@/lib/types";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";

function ResultText({ text }: { text: string }) {
  return (
    <div className="task-result">
      {text.split(/(https:\/\/[^\s<>]+)/g).map((part, index) =>
        part.startsWith("https://") ? (
          <a key={index} href={part} target="_blank" rel="noopener noreferrer">
            {part}
          </a>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </div>
  );
}

export function TasksPanel({
  client,
  owner,
  tasks,
  selectedId,
  onSelect,
  refresh,
}: {
  client: OrinClient;
  owner: string;
  tasks: Task[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  refresh: () => Promise<void>;
}) {
  const [request, setRequest] = useState("");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const selected =
    tasks.find((task) => task.id === selectedId) || tasks[0] || null;
  const visible = useMemo(
    () =>
      tasks.filter((task) =>
        `${task.request} ${task.kind} ${task.status}`
          .toLowerCase()
          .includes(filter.toLowerCase()),
      ),
    [tasks, filter],
  );
  const streamState = useTaskEvents(
    selected?.id || null,
    selected?.status === "running",
    refresh,
  );

  useEffect(() => {
    if (!selected) {
      setUsage([]);
      return;
    }
    let current = true;
    client
      .get<UsageRecord[]>(`/tasks/${encodeURIComponent(selected.id)}/usage`)
      .then((records) => {
        if (current) setUsage(records);
      })
      .catch(() => {
        if (current) setUsage([]);
      });
    return () => {
      current = false;
    };
  }, [client, selected?.id, selected?.status]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!request.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      const created = await client.post<{ id: string }>("/tasks", {
        session_id: `web:${owner}`,
        request: request.trim(),
      });
      onSelect(created.id);
      setRequest("");
      await refresh();
      await client.post(`/tasks/${encodeURIComponent(created.id)}/run`);
      await refresh();
    } catch (failure) {
      setMessage(
        failure instanceof Error ? failure.message : "Could not start the task",
      );
    } finally {
      setBusy(false);
    }
  }

  async function act(path: string) {
    if (!selected) return;
    setBusy(true);
    setMessage("");
    try {
      await client.post(path);
      await refresh();
    } catch (failure) {
      setMessage(
        failure instanceof Error ? failure.message : "Task action failed",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel-stack">
      <section className="surface-card composer-card">
        <SectionHeading
          eyebrow="NEW WORK"
          title="Ask Orin to do something"
          description="Tasks run through the same runtime as Telegram and the CLI."
        />
        <form onSubmit={submit} className="composer-form">
          <label className="sr-only" htmlFor="task-request">
            Task request
          </label>
          <textarea
            id="task-request"
            value={request}
            onChange={(event) => setRequest(event.target.value)}
            placeholder="For example, show my upcoming Calendar events…"
            rows={2}
            maxLength={4000}
          />
          <button
            type="submit"
            className="button button-primary"
            disabled={busy || !request.trim()}
          >
            <Send size={17} />
            {busy ? "Working…" : "Start task"}
          </button>
        </form>
        {message && <Notice kind="error">{message}</Notice>}
      </section>

      <div className="task-layout">
        <section className="surface-card task-list-card">
          <SectionHeading eyebrow="ACTIVITY" title="Task history" />
          <div className="search-field">
            <Search size={17} />
            <label className="sr-only" htmlFor="task-search">
              Filter tasks
            </label>
            <input
              id="task-search"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter tasks"
            />
          </div>
          {visible.length ? (
            <div className="task-list">
              {visible.map((task) => (
                <button
                  key={task.id}
                  type="button"
                  className={`task-list-row ${selected?.id === task.id ? "selected" : ""}`}
                  onClick={() => onSelect(task.id)}
                >
                  <span className="task-list-row-top">
                    <strong>{task.request}</strong>
                    <StatusBadge status={task.status} />
                  </span>
                  <span className="task-list-row-meta">
                    {titleCase(task.kind)} · {formatDate(task.created_at)}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Activity}
              title="Nothing here yet"
              description="Try another search or create a new task."
            />
          )}
        </section>

        <section className="surface-card task-detail-card">
          {selected ? (
            <>
              <div className="task-detail-head">
                <div>
                  <p className="eyebrow">
                    TASK / {shortId(selected.id).toUpperCase()}
                  </p>
                  <h2>{selected.request}</h2>
                </div>
                <StatusBadge status={selected.status} />
              </div>
              <div className="detail-grid">
                <div>
                  <span>Created</span>
                  <strong>{formatDate(selected.created_at)}</strong>
                </div>
                <div>
                  <span>Session</span>
                  <strong>{selected.session_id}</strong>
                </div>
                <div>
                  <span>Workflow</span>
                  <strong>{titleCase(selected.kind)}</strong>
                </div>
                <div>
                  <span>Live events</span>
                  <strong
                    className={streamState === "live" ? "text-success" : ""}
                  >
                    {streamState === "idle" ? "—" : titleCase(streamState)}
                  </strong>
                </div>
              </div>
              {selected.error && (
                <Notice kind="error">
                  Paused after {selected.error}. You can resume this task when
                  its dependency is available.
                </Notice>
              )}
              <div className="task-actions">
                {(selected.status === "pending" ||
                  selected.status === "paused") && (
                  <button
                    type="button"
                    className="button button-primary"
                    disabled={busy}
                    onClick={() =>
                      void act(`/tasks/${encodeURIComponent(selected.id)}/run`)
                    }
                  >
                    <CirclePlay size={17} />
                    {selected.status === "paused" ? "Resume task" : "Run task"}
                  </button>
                )}
                {(selected.status === "pending" ||
                  selected.status === "paused") && (
                  <button
                    type="button"
                    className="button button-quiet"
                    disabled={busy}
                    onClick={() =>
                      void act(
                        `/tasks/${encodeURIComponent(selected.id)}/cancel`,
                      )
                    }
                  >
                    <Ban size={17} />
                    Cancel
                  </button>
                )}
              </div>
              <div className="detail-section">
                <h3>
                  <TerminalSquare size={18} /> Result
                </h3>
                {selected.result ? (
                  <ResultText text={selected.result} />
                ) : (
                  <EmptyState
                    icon={Clock3}
                    title="No result yet"
                    description="Results appear here when the task finishes."
                  />
                )}
              </div>
              <div className="detail-section">
                <h3>
                  <Activity size={18} /> Model usage
                </h3>
                {usage.length ? (
                  <div className="usage-list">
                    {usage.map((record) => (
                      <div className="usage-row" key={record.id}>
                        <span>
                          <strong>{record.model}</strong>
                          <small>{titleCase(record.role)}</small>
                        </span>
                        <span>
                          {formatNumber(
                            (record.input_tokens || 0) +
                              (record.output_tokens || 0),
                          )}{" "}
                          tokens
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">
                    No model call was needed for this task.
                  </p>
                )}
              </div>
            </>
          ) : (
            <EmptyState
              icon={Activity}
              title="Select a task"
              description="Choose a task from the list to inspect its progress and result."
            />
          )}
        </section>
      </div>
    </div>
  );
}
