import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  Layers3,
  type LucideIcon,
} from "lucide-react";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import type { DashboardData, Task } from "@/lib/types";
import { EmptyState, SectionHeading, StatusBadge } from "./ui";

function Metric({
  label,
  value,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  tone?: string;
}) {
  return (
    <div className={`metric-card metric-${tone}`}>
      <div className="metric-top">
        <span>{label}</span>
        <Icon size={20} strokeWidth={1.8} />
      </div>
      <strong>{value}</strong>
    </div>
  );
}

export function OverviewPanel({
  data,
  onSelectTask,
  onOpenTasks,
}: {
  data: DashboardData;
  onSelectTask: (task: Task) => void;
  onOpenTasks: () => void;
}) {
  const completed = data.tasks.filter(
    (task) => task.status === "completed",
  ).length;
  const paused = data.tasks.filter((task) => task.status === "paused").length;
  const running = data.tasks.filter((task) => task.status === "running").length;
  const connected = data.capabilities.filter(
    (source) => source.configured,
  ).length;

  return (
    <div className="panel-stack">
      <section className="welcome-card">
        <div>
          <p className="eyebrow light">YOUR WORKSPACE AT A GLANCE</p>
          <h2>Good to have you here.</h2>
          <p>
            Orin keeps track of the details, so you can focus on what matters
            next.
          </p>
          <button
            type="button"
            className="button button-light"
            onClick={onOpenTasks}
          >
            Start a task <Activity size={17} />
          </button>
        </div>
        <div className="welcome-visual" aria-hidden="true">
          <div className="welcome-ring ring-one" />
          <div className="welcome-ring ring-two" />
          <div className="welcome-core">
            <Layers3 size={32} />
          </div>
        </div>
      </section>

      <div className="metrics-grid">
        <Metric
          label="Total tasks"
          value={formatNumber(data.tasks.length)}
          icon={Activity}
        />
        <Metric
          label="Completed"
          value={formatNumber(completed)}
          icon={CheckCircle2}
          tone="green"
        />
        <Metric
          label="Needs attention"
          value={formatNumber(paused)}
          icon={AlertCircle}
          tone="amber"
        />
        <Metric
          label="Sources configured"
          value={`${connected} / ${data.capabilities.length}`}
          icon={DatabaseZap}
          tone="blue"
        />
      </div>

      <div className="overview-columns">
        <section className="surface-card">
          <SectionHeading
            eyebrow="ACTIVITY"
            title="Recent tasks"
            action={
              <button
                type="button"
                className="text-button"
                onClick={onOpenTasks}
              >
                View all
              </button>
            }
          />
          {data.tasks.length ? (
            <div className="recent-list">
              {data.tasks.slice(0, 6).map((task) => (
                <button
                  type="button"
                  className="recent-row"
                  key={task.id}
                  onClick={() => onSelectTask(task)}
                >
                  <span className={`recent-icon recent-${task.status}`}>
                    <Activity size={17} />
                  </span>
                  <span className="recent-main">
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
              icon={Clock3}
              title="No tasks yet"
              description="Your recent work will appear here after you ask Orin to do something."
            />
          )}
        </section>
        <section className="surface-card compact-card">
          <SectionHeading eyebrow="RUNTIME" title="At this moment" />
          <div className="runtime-fact">
            <span>Active work</span>
            <strong>
              {running} task{running === 1 ? "" : "s"}
            </strong>
          </div>
          <div className="runtime-fact">
            <span>Open approvals</span>
            <strong>
              {
                data.approvals.filter((item) => item.status === "pending")
                  .length
              }
            </strong>
          </div>
          <div className="runtime-fact">
            <span>Scheduled jobs</span>
            <strong>
              {data.schedules.filter((item) => item.status === "active").length}
            </strong>
          </div>
          <div className="runtime-fact">
            <span>Sessions</span>
            <strong>{data.sessions.length}</strong>
          </div>
          <div className="runtime-note">
            <span className="status-dot" /> This view reads from your local Orin
            database.
          </div>
        </section>
      </div>
    </div>
  );
}
