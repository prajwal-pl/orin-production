import { Cpu, Layers3, ServerCog } from "lucide-react";
import { formatDate, formatNumber } from "@/lib/format";
import type { ModelHealth, Session } from "@/lib/types";
import { EmptyState, SectionHeading, StatusBadge } from "./ui";

export function SystemPanel({
  models,
  sessions,
}: {
  models: ModelHealth[];
  sessions: Session[];
}) {
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
              <div className="session-row" key={session.id}>
                <Layers3 size={18} />
                <span>{session.id}</span>
                <small>{formatDate(session.created_at)}</small>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={ServerCog}
            title="No sessions yet"
            description="Sessions appear here when Orin receives a task."
          />
        )}
      </section>
    </div>
  );
}
