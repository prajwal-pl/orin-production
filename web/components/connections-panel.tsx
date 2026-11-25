import { DatabaseZap, LockKeyhole, PlugZap } from "lucide-react";
import type { Capability } from "@/lib/types";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";

export function ConnectionsPanel({
  capabilities,
}: {
  capabilities: Capability[];
}) {
  return (
    <div className="panel-stack">
      <Notice>
        “Configured” means Orin found a local credential and owner grant. It
        does not confirm the provider currently accepts that credential.
      </Notice>
      <section className="surface-card">
        <SectionHeading
          eyebrow="INTEGRATIONS"
          title="Connected sources"
          description="Each source has its own permission boundary and capability."
        />
        {capabilities.length ? (
          <div className="source-grid">
            {capabilities.map((source) => (
              <article className="source-card" key={source.key}>
                <div className="source-top">
                  <span className="source-icon">
                    <PlugZap size={21} />
                  </span>
                  <StatusBadge
                    status={source.configured ? "configured" : "not configured"}
                  />
                </div>
                <h3>
                  {source.key === "github"
                    ? "GitHub"
                    : source.key === "gmail"
                      ? "Gmail"
                      : source.key === "todoist"
                        ? "Todoist"
                        : source.key[0].toUpperCase() + source.key.slice(1)}
                </h3>
                <p>{source.description}</p>
                <div className="source-permission">
                  <LockKeyhole size={14} />
                  <span>{source.capability}</span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={DatabaseZap}
            title="No sources listed"
            description="The local runtime has not reported any capabilities."
          />
        )}
      </section>
    </div>
  );
}
