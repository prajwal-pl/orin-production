"use client";

import { FormEvent, useState } from "react";
import { ArrowUpRight, LockKeyhole, ShieldCheck, Sparkles } from "lucide-react";
import { pairBrowser } from "@/lib/api";
import type { BrowserSession } from "@/lib/types";
import { Notice } from "./ui";

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
        <div className="pair-brand">
          <span className="brand-mark">
            <Sparkles size={21} />
          </span>
          <span>
            orin<span className="brand-period">.</span>
          </span>
        </div>
        <div className="pair-story-content">
          <div className="pair-orbit" aria-hidden="true">
            <div className="pair-orbit-core">
              <Sparkles size={42} />
            </div>
            <i />
            <i />
            <i />
          </div>
          <p className="eyebrow light">YOUR AGENT, IN YOUR HANDS</p>
          <h1>
            A clearer view of
            <br />
            <em>everything Orin does.</em>
          </h1>
          <p>
            Tasks, connections, approvals, and activity in one calm
            place—running on your own computer.
          </p>
        </div>
        <div className="pair-story-foot">
          <ShieldCheck size={17} /> Local runtime · Your data stays on this
          device
        </div>
      </section>
      <section className="pair-form-wrap">
        <div className="pair-form-card">
          <div className="pair-lock">
            <LockKeyhole size={23} />
          </div>
          <p className="eyebrow">LOCAL CONTROL CENTER</p>
          <h2>Pair this browser</h2>
          <p className="muted">
            Enter the one-time code shown in the terminal where you started
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
                placeholder="Paste your code"
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
              <button
                className="button button-primary button-full"
                type="submit"
                disabled={!code.trim() || busy}
              >
                {busy ? "Pairing…" : "Open control center"}
                <ArrowUpRight size={17} />
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
          <p className="pair-hint">
            This page connects only to the Orin service on your computer.
          </p>
        </div>
      </section>
    </div>
  );
}
