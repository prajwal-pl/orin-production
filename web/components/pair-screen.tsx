"use client";

import { FormEvent, useState } from "react";
import {
  ArrowRight,
  Check,
  KeyRound,
  ListChecks,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import { pairBrowser } from "@/lib/api";
import type { BrowserSession } from "@/lib/types";
import { Brand } from "./brand";
import { Notice } from "./ui";
import { ThemeToggle } from "./theme-toggle";

export function PairScreen({
  available,
  onPaired,
}: {
  available: boolean;
  onPaired: (session: BrowserSession) => void;
}) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onPaired(await pairBrowser(code.trim()));
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Could not pair this browser",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="pair-layout">
      <section className="pair-story">
        <Brand />
        <div className="pair-story-content">
          <span className="pair-overline">
            <span className="pulse-dot" /> LOCAL CONTROL CENTER
          </span>
          <h1>
            Your agent.
            <br />
            Your call.
          </h1>
          <p>
            A focused place to give Orin work, inspect what happened, and decide
            what it may do next.
          </p>
          <div className="pair-principles">
            <div>
              <span>
                <ListChecks size={18} />
              </span>
              <strong>Trace every task</strong>
              <small>From request to result</small>
            </div>
            <div>
              <span>
                <ShieldCheck size={18} />
              </span>
              <strong>Approve with context</strong>
              <small>Exact actions, never a blank check</small>
            </div>
            <div>
              <span>
                <LockKeyhole size={18} />
              </span>
              <strong>Keep it local</strong>
              <small>This interface runs on your device</small>
            </div>
          </div>
        </div>
        <div className="pair-story-foot">
          <span className="footer-mark" /> ORIN / PERSONAL RUNTIME
        </div>
      </section>
      <section className="pair-form-wrap">
        <ThemeToggle className="pair-theme-toggle" />
        <div className="pair-form-card">
          <div className="pair-form-icon">
            <KeyRound size={22} />
          </div>
          <p className="eyebrow">STEP 01 / SECURE ACCESS</p>
          <h2>Pair this browser</h2>
          <p className="pair-description">
            Enter the one-time code printed in the terminal where you started
            Orin.
          </p>
          {available ? (
            <form onSubmit={submit} className="pair-form">
              <label htmlFor="pair-code">Pairing code</label>
              <input
                id="pair-code"
                type="text"
                autoComplete="one-time-code"
                autoFocus
                placeholder="Enter your code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
              <button
                className="button button-primary button-full"
                type="submit"
                disabled={!code.trim() || busy}
              >
                {busy ? "Pairing…" : "Open workbench"}
                <ArrowRight size={17} />
              </button>
            </form>
          ) : (
            <Notice kind="error">
              Pairing is unavailable. Restart Orin with{" "}
              <code>uv run python -m orchestration.control_center</code> to get
              a new code.
            </Notice>
          )}
          {error && <Notice kind="error">{error}</Notice>}
          <div className="pair-form-foot">
            <Check size={15} />
            <span>
              One-time code · Private browser session · No cloud dashboard
            </span>
          </div>
        </div>
      </section>
    </div>
  );
}
