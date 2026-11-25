"use client";

import { useState } from "react";
import { Cpu, Layers3, ServerCog, ChartNoAxesCombined } from "lucide-react";
import { formatDate, formatNumber } from "@/lib/format";
import { OrinClient } from "@/lib/api";
import type {
  ModelHealth,
  Session,
  SessionMessage,
  UsageSummary,
} from "@/lib/types";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";

export function SystemPanel({
  models,
  sessions,
  usage,
  client,
}: {
  models: ModelHealth[];
  sessions: Session[];
  usage: UsageSummary[];
  client: OrinClient;
}) {
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [error, setError] = useState("");
  const calls = usage.reduce((total, item) => total + item.calls, 0);
  const tokens = usage.reduce(
    (total, item) =>
      total + (item.input_tokens ?? 0) + (item.output_tokens ?? 0),
    0,
  );

  async function inspectSession(id: string) {
    if (selectedSession === id) {
      setSelectedSession(null);
      return;
    }
    setError("");
    try {
      const records = await client.get<SessionMessage[]>(
        `/sessions/${encodeURIComponent(id)}/messages`,
      );
      setMessages(records);
      setSelectedSession(id);
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not load session",
      );
    }
  }

  return (
    <div className="panel-stack">
      <div className="page-intro">
        <div>
          <p className="eyebrow">RUNTIME OBSERVABILITY</p>
          <h2>Inside Orin</h2>
          <p>
            What the local runtime has observed about models and workspaces.
          </p>
        </div>
        <div className="intro-count">
          <strong>{models.length}</strong>
          <span>model records</span>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      <section className="surface-card">
        <SectionHeading
          eyebrow="INFERENCE"
          title="Models"
          description="Health and quota reflect only what the local runtime has observed."
        />
        {models.length ? (
          <div className="model-list">
            {models.map((model) => (
              <div className="model-row" key={model.model}>
                <span className="model-icon">
                  <Cpu size={20} />
                </span>
                <div className="model-main">
                  <strong>{model.model}</strong>
                  <small>Updated {formatDate(model.updated_at)}</small>
                </div>
                <div className="model-meta">
                  <span>Context</span>
                  <strong>
                    {model.context_window
                      ? formatNumber(model.context_window)
                      : "Unknown"}
                  </strong>
                </div>
                <div className="model-meta">
                  <span>Quota</span>
                  <strong>
                    {model.quota_remaining === null
                      ? "Unknown"
                      : formatNumber(model.quota_remaining)}
                  </strong>
                </div>
                <StatusBadge
                  status={model.healthy ? "available" : "unavailable"}
                />
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Cpu}
            title="No model records"
            description="Model health appears here when a provider is configured."
          />
        )}
      </section>
      <section className="surface-card">
        <SectionHeading
          eyebrow="CONTEXT"
          title="Sessions"
          description="Recent conversation and task contexts stored by Orin."
        />
        {sessions.length ? (
          <div className="session-grid">
            {sessions.slice(0, 12).map((session) => (
              <button
                type="button"
                className={`session-row ${selectedSession === session.id ? "selected" : ""}`}
                key={session.id}
                onClick={() => void inspectSession(session.id)}
                aria-expanded={selectedSession === session.id}
              >
                <Layers3 size={18} />
                <span>{session.id}</span>
                <small>{formatDate(session.created_at)}</small>
              </button>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={ServerCog}
            title="No sessions yet"
            description="Sessions appear here when Orin receives a task."
          />
        )}
        {selectedSession && (
          <div className="session-detail">
            <h3>Session {selectedSession}</h3>
            {messages.length ? (
              messages.map((message) => (
                <p key={message.id}>
                  <strong>
                    {message.role} · {formatDate(message.created_at)}
                  </strong>
                  {message.content}
                </p>
              ))
            ) : (
              <p>No messages in this session yet.</p>
            )}
          </div>
        )}
      </section>
      <section className="surface-card">
        <SectionHeading
          eyebrow="OBSERVED COST"
          title="Model usage"
          description="Counts come from completed local records. Unknown provider token counts are not estimated."
        />
        <div className="usage-summary">
          <div>
            <span>Model calls</span>
            <strong>{formatNumber(calls)}</strong>
          </div>
          <div>
            <span>Observed tokens</span>
            <strong>{formatNumber(tokens)}</strong>
          </div>
          <div>
            <span>Models used</span>
            <strong>{usage.length}</strong>
          </div>
        </div>
        {usage.length ? (
          <div className="management-list">
            {usage.map((item) => (
              <div className="management-row" key={item.model}>
                <div className="management-row-main">
                  <div className="management-row-meta">
                    <strong>{item.model}</strong>
                    <span>Last used {formatDate(item.last_used_at)}</span>
                  </div>
                  <p>
                    {item.calls} calls · {item.successful_calls} succeeded ·{" "}
                    {item.average_latency_ms === null
                      ? "Latency unknown"
                      : `${Math.round(item.average_latency_ms)} ms average`}
                  </p>
                  <small>
                    Input{" "}
                    {item.input_tokens === null
                      ? "unknown"
                      : formatNumber(item.input_tokens)}{" "}
                    · Output{" "}
                    {item.output_tokens === null
                      ? "unknown"
                      : formatNumber(item.output_tokens)}
                  </small>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={ChartNoAxesCombined}
            title="No model usage yet"
            description="Observed calls appear here after Orin runs a model-backed task."
          />
        )}
      </section>
    </div>
  );
}
