"use client";

import { useState } from "react";
import { Check, FileClock, RotateCcw, ShieldCheck, X } from "lucide-react";
import { OrinClient } from "@/lib/api";
import { formatDate, shortId, titleCase } from "@/lib/format";
import type { Action, Approval } from "@/lib/types";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";

export function ApprovalsPanel({
  client,
  approvals,
  actions,
  refresh,
}: {
  client: OrinClient;
  approvals: Approval[];
  actions: Action[];
  refresh: () => Promise<void>;
}) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const sorted = [...approvals].sort(
    (a, b) =>
      (a.status === "pending" ? -1 : 1) - (b.status === "pending" ? -1 : 1) ||
      b.created_at - a.created_at,
  );

  async function change(path: string, id: string) {
    setBusyId(id);
    setMessage("");
    try {
      await client.post(path);
      await refresh();
    } catch (failure) {
      setMessage(
        failure instanceof Error
          ? failure.message
          : "Could not update the action",
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="panel-stack">
      <section className="intro-strip">
        <ShieldCheck size={24} />
        <div>
          <strong>Every write needs your approval.</strong>
          <p>
            Review the exact parameters, account capability, and expiry before
            allowing an action to run.
          </p>
        </div>
      </section>
      {message && <Notice kind="error">{message}</Notice>}
      <section className="surface-card">
        <SectionHeading
          eyebrow="REVIEW QUEUE"
          title="Approvals"
          description={`${approvals.filter((item) => item.status === "pending").length} waiting for review`}
        />
        {sorted.length ? (
          <div className="approval-list">
            {sorted.map((approval) => {
              const action = actions.find(
                (item) => item.approval_id === approval.id,
              );
              const expired = approval.expires_at <= Date.now() / 1000;
              return (
                <article className="approval-card" key={approval.id}>
                  <div className="approval-top">
                    <span className="approval-icon">
                      <ShieldCheck size={20} />
                    </span>
                    <div>
                      <h3>{titleCase(approval.capability)}</h3>
                      <p>
                        Approval {shortId(approval.id)} · Expires{" "}
                        {formatDate(approval.expires_at)}
                      </p>
                    </div>
                    <StatusBadge
                      status={
                        expired && approval.status === "pending"
                          ? "expired"
                          : approval.status
                      }
                    />
                  </div>
                  <div className="parameters-block">
                    <span>Exact action parameters</span>
                    <pre>{JSON.stringify(approval.parameters, null, 2)}</pre>
                  </div>
                  {action && (
                    <p className="approval-linked">
                      Linked action: {shortId(action.id)} ·{" "}
                      {titleCase(action.status)}
                    </p>
                  )}
                  {approval.status === "pending" && !expired && (
                    <div className="approval-actions">
                      <button
                        type="button"
                        className="button button-primary"
                        disabled={busyId === approval.id}
                        onClick={() =>
                          void change(
                            `/approvals/${approval.id}/approve`,
                            approval.id,
                          )
                        }
                      >
                        <Check size={16} />
                        Approve
                      </button>
                      <button
                        type="button"
                        className="button button-quiet"
                        disabled={busyId === approval.id}
                        onClick={() =>
                          void change(
                            `/approvals/${approval.id}/deny`,
                            approval.id,
                          )
                        }
                      >
                        <X size={16} />
                        Deny
                      </button>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState
            icon={ShieldCheck}
            title="No approvals yet"
            description="Actions that need your review will appear here before they can run."
          />
        )}
      </section>
      <section className="surface-card">
        <SectionHeading
          eyebrow="EXTERNAL ACTIONS"
          title="Action history"
          description="Unknown outcomes are held for reconciliation; Orin never silently resends them."
        />
        {actions.length ? (
          <div className="action-list">
            {actions.map((action) => {
              const approval = approvals.find(
                (item) => item.id === action.approval_id,
              );
              return (
                <div className="action-row" key={action.id}>
                  <span className="action-symbol">
                    <FileClock size={19} />
                  </span>
                  <span className="action-main">
                    <strong>{titleCase(action.capability)}</strong>
                    <small>
                      {formatDate(action.created_at)} · {shortId(action.id)}
                    </small>
                  </span>
                  <StatusBadge status={action.status} />
                  {action.status === "prepared" &&
                    approval?.status === "approved" && (
                      <button
                        type="button"
                        className="button button-small"
                        disabled={busyId === action.id}
                        onClick={() =>
                          void change(`/actions/${action.id}/run`, action.id)
                        }
                      >
                        Run approved action
                      </button>
                    )}
                  {action.status === "unknown" && (
                    <button
                      type="button"
                      className="button button-small"
                      disabled={busyId === action.id}
                      onClick={() =>
                        void change(
                          `/actions/${action.id}/reconcile`,
                          action.id,
                        )
                      }
                    >
                      <RotateCcw size={15} />
                      Reconcile
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            icon={FileClock}
            title="No external actions"
            description="Prepared Gmail, Calendar, and Drive writes will appear here."
          />
        )}
      </section>
    </div>
  );
}
