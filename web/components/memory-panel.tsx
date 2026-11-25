"use client";

import { FormEvent, useMemo, useState } from "react";
import { BookOpenText, Plus, Search, Trash2 } from "lucide-react";
import { OrinClient } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { MemoryRecord } from "@/lib/types";
import { EmptyState, Notice, SectionHeading, StatusBadge } from "./ui";

const categories = [
  "episodic",
  "semantic",
  "procedural",
  "preference",
  "working",
];

export function MemoryPanel({
  client,
  memories,
  refresh,
}: {
  client: OrinClient;
  memories: MemoryRecord[];
  refresh: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("preference");
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const visible = useMemo(
    () =>
      memories.filter((memory) =>
        `${memory.content} ${memory.category} ${memory.provenance}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [memories, query],
  );

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    setError("");
    try {
      await client.post("/memories", {
        category,
        content: content.trim(),
        provenance: "user",
      });
      setContent("");
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not save memory",
      );
    } finally {
      setBusy(false);
    }
  }

  async function update(id: string) {
    if (!revision.trim()) return;
    setBusy(true);
    setError("");
    try {
      await client.put(`/memories/${encodeURIComponent(id)}`, {
        content: revision.trim(),
      });
      setEditing(null);
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not update memory",
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Remove this memory from Orin?")) return;
    setBusy(true);
    setError("");
    try {
      await client.delete(`/memories/${encodeURIComponent(id)}`);
      await refresh();
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "Could not remove memory",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel-stack">
      <div className="page-intro">
        <div>
          <p className="eyebrow">LOCAL KNOWLEDGE</p>
          <h2>Memory</h2>
          <p>Inspect and correct what the runtime can recall.</p>
        </div>
        <div className="intro-count">
          <strong>{memories.length}</strong>
          <span>records</span>
        </div>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      <section className="surface-card">
        <SectionHeading
          eyebrow="ADD CONTEXT"
          title="Remember something"
          description="Saved to this owner only. Working memories expire after seven days; episodes after 30 days."
        />
        <form className="management-form" onSubmit={add}>
          <div className="field">
            <label htmlFor="memory-category">Category</label>
            <select
              id="memory-category"
              value={category}
              onChange={(event) => setCategory(event.target.value)}
            >
              {categories.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="memory-content">Memory</label>
            <textarea
              id="memory-content"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              maxLength={8000}
              rows={3}
              placeholder="A useful preference or fact Orin should remember"
            />
          </div>
          <button
            className="button button-primary"
            disabled={busy || !content.trim()}
          >
            <Plus size={16} /> Save memory
          </button>
        </form>
      </section>
      <section className="surface-card">
        <SectionHeading
          eyebrow="INSPECT & CORRECT"
          title="Stored memories"
          description="Search this list, edit a record, or remove it."
          action={<span className="status-badge">{visible.length} shown</span>}
        />
        <label className="management-search">
          <Search size={17} />
          <span className="sr-only">Search memories</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search memories"
          />
        </label>
        {visible.length ? (
          <div className="management-list">
            {visible.map((memory) => (
              <article className="management-row" key={memory.id}>
                <div className="management-row-main">
                  <div className="management-row-meta">
                    <StatusBadge status={memory.category} />
                    <span>{formatDate(memory.created_at)}</span>
                    {memory.expires_at && (
                      <span>Expires {formatDate(memory.expires_at)}</span>
                    )}
                  </div>
                  {editing === memory.id ? (
                    <div className="management-edit">
                      <textarea
                        aria-label="Edit memory"
                        rows={3}
                        maxLength={8000}
                        value={revision}
                        onChange={(event) => setRevision(event.target.value)}
                      />
                      <div>
                        <button
                          className="button button-small"
                          disabled={busy || !revision.trim()}
                          onClick={() => void update(memory.id)}
                        >
                          Save change
                        </button>
                        <button
                          className="text-button"
                          onClick={() => setEditing(null)}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p>{memory.content}</p>
                  )}
                  <small>Source: {memory.provenance}</small>
                </div>
                <div className="management-actions">
                  <button
                    className="button button-small"
                    disabled={busy}
                    onClick={() => {
                      setEditing(memory.id);
                      setRevision(memory.content);
                    }}
                  >
                    Edit
                  </button>
                  <button
                    className="icon-button"
                    disabled={busy}
                    aria-label="Remove memory"
                    title="Remove memory"
                    onClick={() => void remove(memory.id)}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={BookOpenText}
            title={query ? "No matching memories" : "No memories yet"}
            description={
              query
                ? "Try a different search."
                : "Save a preference or complete a supported task to build memory."
            }
          />
        )}
      </section>
    </div>
  );
}
