"use client";

import { useState } from "react";
import { FolderLock, Info, LockKeyhole, Plug2 } from "lucide-react";
import { OrinClient } from "@/lib/api";
import type { AccessGrant, Capability, FilesystemRoot } from "@/lib/types";
import { ServiceMark, serviceName } from "./service-mark";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";
import { formatDate } from "@/lib/format";

function accessLabel(operation: string) {
  return operation === "write" ? "Write access" : "Read access";
}

export function ConnectionsPanel({
  capabilities,
  grants,
  roots,
  client,
  refresh,
}: {
  capabilities: Capability[];
  grants: AccessGrant[];
  roots: FilesystemRoot[];
  client: OrinClient;
  refresh: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const configured = capabilities.filter((item) => item.configured);
  const remaining = capabilities.filter((item) => !item.configured);

  async function disconnect(source: Capability) {
    if (
      !window.confirm(
        `Remove the local ${serviceName(source.key)} OAuth credential? Existing task history stays available.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await client.post(
        `/connections/${encodeURIComponent(source.key)}/disconnect`,
      );
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Could not disconnect source",
      );
    } finally {
      setBusy(false);
    }
  }

  async function revokeGrant(grant: AccessGrant) {
    const key = `grant:${grant.capability}:${grant.operation}`;
    if (
      !window.confirm(
        `Revoke ${accessLabel(grant.operation).toLowerCase()} for ${grant.capability}? Tasks needing it will stop until you grant it again.`,
      )
    )
      return;
    setBusyKey(key);
    setError("");
    try {
      await client.delete(
        `/policy/grants?capability=${encodeURIComponent(grant.capability)}&operation=${grant.operation}`,
      );
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not revoke grant",
      );
    } finally {
      setBusyKey(null);
    }
  }

  async function revokeRoot(root: FilesystemRoot) {
    const key = `root:${root.path}:${root.operation}`;
    if (
      !window.confirm(
        `Revoke ${accessLabel(root.operation).toLowerCase()} for ${root.path}? Files under this root become unavailable.`,
      )
    )
      return;
    setBusyKey(key);
    setError("");
    try {
      await client.delete(
        `/policy/roots?path=${encodeURIComponent(root.path)}&operation=${root.operation}`,
      );
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not revoke root",
      );
    } finally {
      setBusyKey(null);
    }
  }

  const rows = (sources: Capability[]) =>
    sources.map((source) => (
      <div className="source-row" key={source.key}>
        <ServiceMark source={source.key} size={20} />
        <div className="source-main">
          <strong>{serviceName(source.key)}</strong>
          <small>{source.description}</small>
          {source.auth_method && (
            <small>
              Credential:{" "}
              {source.auth_method === "oauth"
                ? "OS credential store"
                : "local environment"}
            </small>
          )}
          {source.last_success_at && (
            <small>
              Last successful read {formatDate(source.last_success_at)}
            </small>
          )}
        </div>
        <span className="source-scope">
          <LockKeyhole size={14} />{" "}
          {source.read_only ? "Read only" : "Scoped access"}
        </span>
        <StatusBadge
          status={source.configured ? "configured" : "not configured"}
        />
        {source.auth_method === "oauth" && source.configured && (
          <button
            className="button button-small"
            disabled={busy}
            onClick={() => void disconnect(source)}
          >
            Disconnect
          </button>
        )}
      </div>
    ));

  return (
    <div className="panel-stack">
      <div className="page-intro">
        <div>
          <p className="eyebrow">SERVICE DIRECTORY</p>
          <h2>What Orin can reach</h2>
          <p>Each source has its own credential and permission boundary.</p>
        </div>
        <div className="intro-count">
          <strong>{configured.length}</strong>
          <span>of {capabilities.length} configured</span>
        </div>
      </div>
      <div className="inline-info">
        <Info size={17} />
        <span>
          <strong>Configured is a local state.</strong> It means a credential
          and owner grant exist here. Provider access is checked when a task
          runs.
        </span>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      <p className="setup-hint">
        Need to add a source? Connection setup is currently done from the Orin
        project terminal. The README lists each OAuth and token command.
      </p>
      <section className="surface-card source-section">
        <SectionHeading
          eyebrow="READY FOR REQUESTS"
          title="Configured sources"
          description="Available to read when the provider accepts the credential."
        />
        {configured.length ? (
          <div className="source-list">{rows(configured)}</div>
        ) : (
          <EmptyState
            icon={Plug2}
            title="No sources configured"
            description="Connect a source locally to give Orin access to useful context."
          />
        )}
      </section>
      {remaining.length > 0 && (
        <section className="surface-card source-section">
          <SectionHeading
            eyebrow="AVAILABLE"
            title="Other sources"
            description="These integrations need a local credential and owner grant."
          />
          <div className="source-list">{rows(remaining)}</div>
        </section>
      )}
      <section className="surface-card source-section">
        <SectionHeading
          eyebrow="LOCAL ACCESS CONTROL"
          title="Owner grants"
          description="Filesystem tools, terminal, browser, MCP, and content search are separate from source credentials. Revoke any grant you no longer need."
        />
        {grants.length || roots.length ? (
          <div className="source-list">
            {grants.map((grant) => {
              const key = `grant:${grant.capability}:${grant.operation}`;
              return (
                <div className="source-row" key={key}>
                  <div className="source-main">
                    <strong>{grant.capability}</strong>
                    <small>
                      Capability grant stored for this owner. Actions still need
                      an exact approval.
                    </small>
                  </div>
                  <span className="source-scope">
                    <LockKeyhole size={14} /> {accessLabel(grant.operation)}
                  </span>
                  <button
                    className="button button-small"
                    disabled={busyKey === key}
                    onClick={() => void revokeGrant(grant)}
                  >
                    Revoke
                  </button>
                </div>
              );
            })}
            {roots.map((root) => {
              const key = `root:${root.path}:${root.operation}`;
              return (
                <div className="source-row" key={key}>
                  <div className="source-main">
                    <strong>{root.path}</strong>
                    <small>Approved filesystem root</small>
                  </div>
                  <span className="source-scope">
                    <FolderLock size={14} /> {accessLabel(root.operation)}
                  </span>
                  <button
                    className="button button-small"
                    disabled={busyKey === key}
                    onClick={() => void revokeRoot(root)}
                  >
                    Revoke
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            icon={LockKeyhole}
            title="No local grants"
            description="Grant capabilities through the local API when a workflow needs them."
          />
        )}
      </section>
    </div>
  );
}
