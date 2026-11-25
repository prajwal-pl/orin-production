"use client";

import { FormEvent, useState } from "react";
import { Sparkles } from "lucide-react";
import { OrinClient } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { SkillMetric, SkillVersion } from "@/lib/types";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";

function procedure(skill: SkillVersion): string {
  try {
    const parsed = JSON.parse(skill.procedure);
    return (
      (parsed.priority_reasons ?? parsed.source_order ?? []).join(" → ") ||
      "Default grouping"
    );
  } catch {
    return "Procedure unavailable";
  }
}

function result(skill: SkillVersion): string | null {
  try {
    const evaluation = JSON.parse(skill.evaluation ?? "null");
    const candidate = evaluation?.candidate ?? evaluation;
    return candidate
      ? `${candidate.passed}/${candidate.total} fixture checks`
      : null;
  } catch {
    return null;
  }
}

export function SkillsPanel({
  client,
  skills,
  metrics,
  refresh,
}: {
  client: OrinClient;
  skills: SkillVersion[];
  metrics: SkillMetric[];
  refresh: () => Promise<void>;
}) {
  const [kind, setKind] = useState<"briefing" | "github">("briefing");
  const [order, setOrder] = useState("calendar, gmail, drive, github");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const metricById = new Map(metrics.map((metric) => [metric.id, metric]));

  async function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = order
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await client.post(
        kind === "briefing" ? "/skills/briefing" : "/skills/custom",
        kind === "briefing"
          ? { source_order: values }
          : { priority_reasons: values },
      );
      setNotice(
        "Proposal saved. Review its version and fixture result before activation.",
      );
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not propose skill",
      );
    } finally {
      setBusy(false);
    }
  }

  async function activate(skill: SkillVersion) {
    if (
      !window.confirm(
        `Activate ${skill.name} version ${skill.version}? This also deactivates the current version.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await client.post(`/skills/${encodeURIComponent(skill.id)}/activate`);
      setNotice(
        `Version ${skill.version} is active. An earlier version can be activated to roll back.`,
      );
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not activate skill",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel-stack">
      <div className="page-intro">
        <div>
          <p className="eyebrow">REUSABLE PROCEDURES</p>
          <h2>Skills</h2>
          <p>
            Versioned instructions; activating an earlier version rolls back.
          </p>
        </div>
        <div className="intro-count">
          <strong>{skills.length}</strong>
          <span>versions</span>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {notice && <Notice kind="success">{notice}</Notice>}
      <section className="surface-card">
        <SectionHeading
          eyebrow="PROPOSE"
          title="Create a version"
          description="Declarative source or priority order. Orin validates it against local fixtures before activation."
        />
        <form className="management-form" onSubmit={propose}>
          <div className="field">
            <label htmlFor="skill-kind">Procedure</label>
            <select
              id="skill-kind"
              value={kind}
              onChange={(event) => {
                const next = event.target.value as "briefing" | "github";
                setKind(next);
                setOrder(
                  next === "briefing"
                    ? "calendar, gmail, drive, github"
                    : "security_alert, mention, team_mention, assign, review_requested",
                );
              }}
            >
              <option value="briefing">Daily briefing source order</option>
              <option value="github">GitHub notification priority</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="skill-order">Comma separated order</label>
            <input
              id="skill-order"
              value={order}
              onChange={(event) => setOrder(event.target.value)}
            />
          </div>
          <button
            className="button button-primary"
            disabled={busy || !order.trim()}
          >
            Propose version
          </button>
        </form>
      </section>
      <section className="surface-card">
        <SectionHeading
          eyebrow="VERSION HISTORY"
          title="Review and activate"
          description="Each row shows its exact procedure, local evaluation, and observed uses."
        />
        {skills.length ? (
          <div className="management-list">
            {skills.map((skill) => {
              const metric = metricById.get(skill.id);
              return (
                <article className="management-row" key={skill.id}>
                  <div className="management-row-main">
                    <div className="management-row-meta">
                      <strong>
                        {skill.name.replaceAll("_", " ")} · v{skill.version}
                      </strong>
                      <StatusBadge status={skill.status} />
                      <span>{skill.kind}</span>
                    </div>
                    <p>{procedure(skill)}</p>
                    <small>
                      {result(skill) ?? "No fixture result"} ·{" "}
                      {metric?.task_count ?? 0} uses ·{" "}
                      {metric?.corrections ?? 0} corrections ·{" "}
                      {formatDate(skill.created_at)}
                    </small>
                  </div>
                  <div className="management-actions">
                    {skill.status !== "active" && (
                      <button
                        className="button button-small"
                        disabled={busy}
                        onClick={() => void activate(skill)}
                      >
                        {skill.status === "inactive" ? "Roll back" : "Activate"}
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState
            icon={Sparkles}
            title="No skills yet"
            description="A supported task will register the first built-in procedure."
          />
        )}
      </section>
    </div>
  );
}
