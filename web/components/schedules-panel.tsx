"use client";

import { FormEvent, useState } from "react";
import { CalendarClock, Plus, X } from "lucide-react";
import { OrinClient } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Schedule } from "@/lib/types";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";

export function SchedulesPanel({
  client,
  owner,
  schedules,
  refresh,
}: {
  client: OrinClient;
  owner: string;
  schedules: Schedule[];
  refresh: () => Promise<void>;
}) {
  const [request, setRequest] = useState("");
  const [recurrence, setRecurrence] = useState<"once" | "daily">("once");
  const [runAt, setRunAt] = useState("");
  const [dailyTime, setDailyTime] = useState("09:00");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const body =
        recurrence === "once"
          ? {
              session_id: `web:${owner}`,
              request: request.trim(),
              recurrence,
              timezone,
              run_at: new Date(runAt).toISOString(),
              misfire_policy: "run_once",
            }
          : {
              session_id: `web:${owner}`,
              request: request.trim(),
              recurrence,
              timezone,
              hour: Number(dailyTime.split(":")[0]),
              minute: Number(dailyTime.split(":")[1]),
              misfire_policy: "run_once",
            };
      await client.post("/schedules", body);
      setRequest("");
      setRunAt("");
      await refresh();
      setMessage(
        "Schedule saved. The local schedule worker dispatches due jobs.",
      );
    } catch (failure) {
      setMessage(
        failure instanceof Error
          ? failure.message
          : "Could not create schedule",
      );
    } finally {
      setBusy(false);
    }
  }

  async function cancel(id: string) {
    setBusy(true);
    setMessage("");
    try {
      await client.post(`/schedules/${id}/cancel`);
      await refresh();
    } catch (failure) {
      setMessage(
        failure instanceof Error
          ? failure.message
          : "Could not cancel schedule",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel-stack">
      <section className="surface-card">
        <SectionHeading
          eyebrow="AUTOMATION"
          title="Create a schedule"
          description="Run an existing read workflow once or every day. The local worker must be running when it is due."
        />
        <form className="schedule-form" onSubmit={submit}>
          <div className="field full">
            <label htmlFor="schedule-request">What should Orin do?</label>
            <input
              id="schedule-request"
              required
              maxLength={4000}
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              placeholder="Daily briefing"
            />
          </div>
          <div className="field">
            <label htmlFor="schedule-frequency">Frequency</label>
            <select
              id="schedule-frequency"
              value={recurrence}
              onChange={(event) =>
                setRecurrence(event.target.value as "once" | "daily")
              }
            >
              <option value="once">One time</option>
              <option value="daily">Every day</option>
            </select>
          </div>
          {recurrence === "once" ? (
            <div className="field">
              <label htmlFor="schedule-when">Run at</label>
              <input
                id="schedule-when"
                type="datetime-local"
                required
                value={runAt}
                onChange={(event) => setRunAt(event.target.value)}
              />
            </div>
          ) : (
            <div className="field">
              <label htmlFor="schedule-time">Local time</label>
              <input
                id="schedule-time"
                type="time"
                required
                value={dailyTime}
                onChange={(event) => setDailyTime(event.target.value)}
              />
            </div>
          )}
          <div className="schedule-form-foot">
            <span>Time zone: {timezone}</span>
            <button
              type="submit"
              className="button button-primary"
              disabled={busy || !request.trim()}
            >
              <Plus size={17} />
              Save schedule
            </button>
          </div>
        </form>
        {message && (
          <Notice
            kind={message.startsWith("Schedule saved") ? "success" : "error"}
          >
            {message}
          </Notice>
        )}
      </section>
      <section className="surface-card">
        <SectionHeading eyebrow="YOUR AUTOMATIONS" title="Scheduled jobs" />
        {schedules.length ? (
          <div className="schedule-list">
            {schedules.map((job) => (
              <div className="schedule-row" key={job.id}>
                <span className="schedule-icon">
                  <CalendarClock size={19} />
                </span>
                <div className="schedule-main">
                  <strong>{job.request}</strong>
                  <small>
                    {job.recurrence === "daily" ? "Daily" : "One time"} · Next{" "}
                    {formatDate(job.next_run_at)} · {job.timezone}
                  </small>
                </div>
                <StatusBadge status={job.status} />
                {job.status === "active" && (
                  <button
                    type="button"
                    className="icon-button"
                    title="Cancel schedule"
                    aria-label={`Cancel ${job.request}`}
                    disabled={busy}
                    onClick={() => void cancel(job.id)}
                  >
                    <X size={17} />
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={CalendarClock}
            title="Nothing scheduled"
            description="Create a one-time or daily read task to see it here."
          />
        )}
      </section>
    </div>
  );
}
