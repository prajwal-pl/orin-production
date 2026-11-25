import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Clock3,
  ShieldAlert,
  Zap,
} from "lucide-react";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import type { DashboardData, Task } from "@/lib/types";
import { ServiceMark, serviceName } from "./service-mark";
import { TaskComposer } from "./task-composer";
import { EmptyState, SectionHeading, StatusBadge } from "./ui";

export function OverviewPanel({
  data,
  onSelectTask,
  onOpenTasks,
  onOpenApprovals,
  onOpenConnections,
  onOpenSchedules,
  onCreateTask,
}: {
  data: DashboardData;
  onSelectTask: (task: Task) => void;
  onOpenTasks: () => void;
  onOpenApprovals: () => void;
  onOpenConnections: () => void;
  onOpenSchedules: () => void;
  onCreateTask: (request: string) => Promise<void>;
}) {
  const completed = data.tasks.filter(
    (task) => task.status === "completed",
  ).length;
  const running = data.tasks.filter((task) => task.status === "running").length;
  const paused = data.tasks.filter((task) => task.status === "paused");
  const approvals = data.approvals.filter((item) => item.status === "pending");
  const configured = data.capabilities.filter((source) => source.configured);
  const nextSchedule = data.schedules
    .filter((job) => job.status === "active")
    .sort((a, b) => a.next_run_at.localeCompare(b.next_run_at))[0];

  return (
    <div className="overview-page">
      <div className="overview-summary" aria-label="Workspace summary">
        <div>
          <span>COMPLETED</span>
          <strong>{formatNumber(completed)}</strong>
          <small>tasks</small>
        </div>
        <div>
          <span>IN PROGRESS</span>
          <strong>{formatNumber(running)}</strong>
          <small>right now</small>
        </div>
        <div>
          <span>NEEDS ATTENTION</span>
          <strong>{formatNumber(paused.length + approvals.length)}</strong>
          <small>items</small>
        </div>
        <div>
          <span>CONNECTED</span>
          <strong>
            {formatNumber(configured.length)}
            <em>/{data.capabilities.length}</em>
          </strong>
          <small>sources</small>
        </div>
      </div>

      <div className="overview-layout">
        <div className="overview-primary">
          <TaskComposer onSubmit={onCreateTask} />
          <section className="surface-card activity-panel">
            <SectionHeading
              eyebrow="RECENT WORK"
              title="Activity"
              description="A trace of what Orin has handled."
              action={
                <button
                  type="button"
                  className="text-button"
                  onClick={onOpenTasks}
                >
                  All activity <ArrowRight size={15} />
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
                      <span />
                    </span>
                    <span className="recent-main">
                      <strong>{task.request}</strong>
                      <small>
                        {titleCase(task.kind)} <span>·</span>{" "}
                        {formatDate(task.created_at)}
                      </small>
                    </span>
                    <StatusBadge status={task.status} />
                    <ArrowUpRight className="row-arrow" size={16} />
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={Clock3}
                title="Nothing in the activity log yet"
                description="Start with a briefing or ask Orin about a connected service."
              />
            )}
          </section>
        </div>

        <aside className="overview-context" aria-label="Workspace context">
          <section className="attention-panel">
            <div className="context-heading">
              <span className="context-icon">
                <ShieldAlert size={18} />
              </span>
              <div>
                <p>IN YOUR HANDS</p>
                <h2>Needs attention</h2>
              </div>
            </div>
            {approvals.length || paused.length ? (
              <div className="attention-list">
                {approvals.length > 0 && (
                  <button type="button" onClick={onOpenApprovals}>
                    <span className="attention-number">{approvals.length}</span>
                    <span>
                      <strong>Actions to review</strong>
                      <small>Check exact parameters before approval</small>
                    </span>
                    <ArrowRight size={16} />
                  </button>
                )}
                {paused.length > 0 && (
                  <button type="button" onClick={() => onSelectTask(paused[0])}>
                    <span className="attention-number">{paused.length}</span>
                    <span>
                      <strong>Paused tasks</strong>
                      <small>Resume when dependencies are ready</small>
                    </span>
                    <ArrowRight size={16} />
                  </button>
                )}
              </div>
            ) : (
              <div className="all-clear">
                <span>
                  <Check size={18} />
                </span>
                <strong>All clear</strong>
                <p>No pending decisions or paused work.</p>
              </div>
            )}
          </section>

          <section className="surface-card context-card">
            <div className="context-card-head">
              <div>
                <p className="eyebrow">AVAILABLE TO ORIN</p>
                <h2>Connections</h2>
              </div>
              <button
                type="button"
                aria-label="View connections"
                onClick={onOpenConnections}
              >
                <ArrowUpRight size={18} />
              </button>
            </div>
            <div className="connection-list">
              {configured.length ? (
                configured.slice(0, 4).map((source) => (
                  <div className="connection-row" key={source.key}>
                    <ServiceMark source={source.key} />
                    <span>{serviceName(source.key)}</span>
                    <span className="connection-ready">Configured</span>
                  </div>
                ))
              ) : (
                <p className="context-empty">
                  No sources configured yet. Add a connection to give Orin
                  useful context.
                </p>
              )}
            </div>
            <button
              type="button"
              className="context-link"
              onClick={onOpenConnections}
            >
              {configured.length} of {data.capabilities.length} sources
              configured <ArrowRight size={14} />
            </button>
          </section>

          <section className="surface-card context-card next-run-card">
            <div className="context-card-head">
              <div>
                <p className="eyebrow">UP NEXT</p>
                <h2>Automation</h2>
              </div>
              <button
                type="button"
                aria-label="View automations"
                onClick={onOpenSchedules}
              >
                <ArrowUpRight size={18} />
              </button>
            </div>
            {nextSchedule ? (
              <div className="next-run">
                <span className="next-run-icon">
                  <Zap size={17} />
                </span>
                <strong>{nextSchedule.request}</strong>
                <small>
                  {formatDate(nextSchedule.next_run_at)} ·{" "}
                  {nextSchedule.timezone}
                </small>
              </div>
            ) : (
              <div className="next-run empty">
                <span className="next-run-icon">
                  <Zap size={17} />
                </span>
                <strong>No upcoming jobs</strong>
                <small>Set a schedule for recurring work.</small>
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
