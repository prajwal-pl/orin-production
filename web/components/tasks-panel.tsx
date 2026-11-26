"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Ban,
  CirclePlay,
  Clock3,
  FileText,
  Search,
  Signal,
  TerminalSquare,
} from "lucide-react";
import { OrinClient } from "@/lib/api";
import { formatDate, formatNumber, shortId, titleCase } from "@/lib/format";
import { useTaskEvents } from "@/lib/use-dashboard";
import type { Task, UsageRecord } from "@/lib/types";
import { TaskComposer } from "./task-composer";
import { EmptyState, Notice, StatusBadge } from "./ui";

const filters = ["All", "Running", "Paused", "Completed"] as const;
type TaskFilter = (typeof filters)[number];

function ResultText({ text }: { text: string }) {
  return (
    <div className="task-result">
      {text.split(/(https:\/\/[^\s<>]+)/g).map((part, index) =>
        part.startsWith("https://") ? (
          <a key={index} href={part} target="_blank" rel="noopener noreferrer">
            {part} <ArrowUpRight size={13} />
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
  tasks,
  selectedId,
  onSelect,
  refresh,
  onCreateTask,
}: {
  client: OrinClient;
  tasks: Task[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  refresh: () => Promise<void>;
  onCreateTask: (request: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<TaskFilter>("All");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const selected =
    tasks.find((task) => task.id === selectedId) || tasks[0] || null;
  const interrupted =
    selected?.error === "Cancelled" || selected?.error === "Interrupted";
  const visible = useMemo(
    () =>
      tasks.filter((task) => {
        const matchesQuery = `${task.request} ${task.kind} ${task.status}`
          .toLowerCase()
          .includes(query.toLowerCase());
        const matchesFilter =
          filter === "All" ||
          (filter === "Running"
            ? ["running", "pending"].includes(task.status)
            : task.status === filter.toLowerCase());
        return matchesQuery && matchesFilter;
      }),
    [tasks, query, filter],
  );
  const streamState = useTaskEvents(
    selected?.id || null,
    Boolean(selected && ["pending", "running"].includes(selected.status)),
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
    <div className="tasks-page">
      <TaskComposer onSubmit={onCreateTask} compact />
      {message && <Notice kind="error">{message}</Notice>}
      <div className="task-workspace">
        <section className="surface-card task-index" aria-label="Task history">
          <div className="task-index-head">
            <div>
              <p className="eyebrow">WORK LOG</p>
              <h2>
                Task history <span>{tasks.length}</span>
              </h2>
            </div>
          </div>
          <div className="search-field">
            <Search size={17} />
            <label className="sr-only" htmlFor="task-search">
              Filter tasks
            </label>
            <input
              id="task-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search tasks"
            />
          </div>
          <div className="filter-bar" aria-label="Filter by status">
            {filters.map((item) => (
              <button
                type="button"
                key={item}
                className={filter === item ? "selected" : ""}
                aria-pressed={filter === item}
                onClick={() => setFilter(item)}
              >
                {item}
              </button>
            ))}
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
                  <span className={`task-list-state state-${task.status}`} />
                  <span className="task-list-copy">
                    <strong>{task.request}</strong>
                    <small>
                      {titleCase(task.kind)} · {formatDate(task.created_at)}
                    </small>
                  </span>
                  <StatusBadge status={task.status} />
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Search}
              title="No matching tasks"
              description="Try another search or select a different status."
            />
          )}
        </section>

        <section
          className="surface-card task-inspector"
          aria-label="Task details"
        >
          {selected ? (
            <>
              <div className="inspector-top">
                <span>RUN / {shortId(selected.id).toUpperCase()}</span>
                <StatusBadge status={selected.status} />
              </div>
              <div className="task-detail-head">
                <h2>{selected.request}</h2>
                <p>
                  {titleCase(selected.kind)} · Started{" "}
                  {formatDate(selected.created_at)}
                </p>
              </div>
              <div className="task-detail-meta">
                <span>
                  <Clock3 size={15} /> Updated {formatDate(selected.updated_at)}
                </span>
                <span>
                  <FileText size={15} /> {selected.session_id}
                </span>
                {selected.status === "running" && (
                  <span
                    className={
                      streamState === "live"
                        ? "stream-live"
                        : "stream-reconnecting"
                    }
                  >
                    <Signal size={15} />{" "}
                    {streamState === "live" ? "Live updates" : "Reconnecting"}
                  </span>
                )}
              </div>
              {selected.error && (
                <Notice kind="error">
                  {interrupted
                    ? "This run was interrupted before it finished. Resume it to continue from the last checkpoint."
                    : `Paused after ${selected.error}. You can resume when its dependency is available.`}
                </Notice>
              )}
              {(selected.status === "pending" ||
                selected.status === "paused") && (
                <div className="task-actions">
                  <button
                    type="button"
                    className="button button-primary"
                    disabled={busy}
                    onClick={() =>
                      void act(`/tasks/${encodeURIComponent(selected.id)}/run`)
                    }
                  >
                    <CirclePlay size={17} />{" "}
                    {selected.status === "paused" ? "Resume task" : "Run task"}
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={busy}
                    onClick={() =>
                      void act(
                        `/tasks/${encodeURIComponent(selected.id)}/cancel`,
                      )
                    }
                  >
                    <Ban size={16} /> Cancel
                  </button>
                </div>
              )}
              <div className="inspector-section">
                <div className="inspector-section-head">
                  <span className="section-icon">
                    <TerminalSquare size={17} />
                  </span>
                  <div>
                    <h3>Result</h3>
                    <p>Orin&apos;s final response to this task</p>
                  </div>
                </div>
                {selected.result ? (
                  <ResultText text={selected.result} />
                ) : (
                  <EmptyState
                    icon={Clock3}
                    title="Waiting for a result"
                    description="The response will appear here when the task finishes."
                  />
                )}
              </div>
              <div className="inspector-section usage-section">
                <div className="inspector-section-head">
                  <span className="section-icon">
                    <Signal size={17} />
                  </span>
                  <div>
                    <h3>Model usage</h3>
                    <p>Recorded inference for this run</p>
                  </div>
                </div>
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
              icon={FileText}
              title="Choose a task"
              description="Select a run from the work log to see its result and usage."
            />
          )}
        </section>
      </div>
    </div>
  );
}
