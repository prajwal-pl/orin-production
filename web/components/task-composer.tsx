"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  ListTodo,
  Mail,
  Sparkle,
} from "lucide-react";

const suggestions = [
  { label: "Daily briefing", request: "Daily briefing", icon: Sparkle },
  {
    label: "Upcoming events",
    request: "Show my upcoming Calendar events",
    icon: CalendarDays,
  },
  { label: "Unread mail", request: "Show my unread Gmail inbox", icon: Mail },
  { label: "Follow-ups", request: "Find my follow-ups", icon: ListTodo },
];

export function TaskComposer({
  onSubmit,
  compact = false,
}: {
  onSubmit: (request: string) => Promise<void>;
  compact?: boolean;
}) {
  const [request, setRequest] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    function focusOnSlash(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (
        event.key !== "/" ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        target?.matches("input, textarea, select, [contenteditable='true']")
      )
        return;
      event.preventDefault();
      inputRef.current?.focus();
    }
    window.addEventListener("keydown", focusOnSlash);
    return () => window.removeEventListener("keydown", focusOnSlash);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = request.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      await onSubmit(value);
      setRequest("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={`composer ${compact ? "composer-compact" : ""}`}
      aria-label="New task"
    >
      {!compact && (
        <div className="composer-intro">
          <span className="composer-kicker">
            <span className="pulse-dot" /> READY FOR A REQUEST
          </span>
          <h2>What can Orin take care of?</h2>
          <p>Give it a task. Follow each step, source, and result here.</p>
        </div>
      )}
      <form onSubmit={submit}>
        <label className="sr-only" htmlFor="task-request">
          Task request
        </label>
        <textarea
          ref={inputRef}
          id="task-request"
          value={request}
          onChange={(event) => setRequest(event.target.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="Ask Orin to prepare a briefing, review your inbox, find a file…"
          rows={compact ? 2 : 3}
          maxLength={4000}
        />
        <div className="composer-footer">
          <span className="composer-shortcut">
            <kbd>/</kbd> to focus <span className="shortcut-separator">·</span>{" "}
            <kbd>Ctrl</kbd> / <kbd>⌘</kbd> + <kbd>Enter</kbd> to run
          </span>
          <button
            type="submit"
            className="button button-primary"
            disabled={busy || !request.trim()}
          >
            {busy ? "Starting…" : "Run task"}
            <ArrowUpRight size={17} />
          </button>
        </div>
      </form>
      {!compact && (
        <div className="suggestions" aria-label="Try a request">
          <span>TRY</span>
          {suggestions.map(({ label, request: value, icon: Icon }) => (
            <button
              key={label}
              type="button"
              onClick={() => {
                setRequest(value);
                inputRef.current?.focus();
              }}
            >
              <Icon size={15} /> {label}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
