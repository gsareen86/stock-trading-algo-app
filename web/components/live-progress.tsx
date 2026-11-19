"use client";

import { useCallback, useEffect, useState } from "react";

export type ProgressStep = {
  id: string;
  label: string;
};

export type SseProgressEvent = {
  step: string;
  label: string;
  completed?: number | null;
  total?: number | null;
  elapsed_seconds?: number;
};

const LOST_CONNECTION =
  "Lost the live progress connection. The run continues on the server; refresh in a few minutes to see its result.";

export function useSseStream<T = Record<string, unknown>>() {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<SseProgressEvent | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000));
    }, 500);
    return () => window.clearInterval(timer);
  }, [running]);

  const start = useCallback(
    async (
      url: string,
      payload: Record<string, unknown> = {},
      onComplete?: (data: T) => void,
    ) => {
      setRunning(true);
      setElapsed(0);
      setError(null);
      setResult(null);
      setProgress({ step: "starting", label: "Connecting to runner…" });
      let streamOpened = false;

      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          setError(body.detail ?? `HTTP ${res.status}`);
          return null;
        }
        if (!res.body) {
          setError("Streaming response had no body.");
          return null;
        }

        streamOpened = true;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let finalData: T | null = null;
        // Set by `complete` or `error`. Reaching the end of the body without one means the
        // connection dropped, not that the run ended.
        let sawTerminal = false;

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            let eventType = "message";
            const dataLines: string[] = [];
            for (const line of frame.split("\n")) {
              if (line.startsWith("event:")) {
                eventType = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                dataLines.push(line.slice(5).trim());
              }
            }
            if (dataLines.length === 0) continue;
            const parsed = JSON.parse(dataLines.join("\n"));

            if (eventType === "progress") {
              setProgress(parsed as SseProgressEvent);
            } else if (eventType === "error") {
              sawTerminal = true;
              // The backend's error event carries `error`; `detail` is FastAPI's HTTP shape.
              setError(parsed.error ?? parsed.detail ?? "Stream failed");
            } else if (eventType === "complete") {
              sawTerminal = true;
              finalData = (parsed.result ?? parsed) as T;
              setResult(finalData);
            }
          }
        }
        if (!sawTerminal) {
          setError(LOST_CONNECTION);
          return null;
        }
        if (finalData && onComplete) {
          onComplete(finalData);
        }
        return finalData;
      } catch (err) {
        // Once the stream has opened, a failure is the connection, not the run: the server
        // finishes and records the run whether or not anyone is watching.
        setError(
          streamOpened
            ? LOST_CONNECTION
            : err instanceof Error
              ? err.message
              : "Could not reach the server.",
        );
        return null;
      } finally {
        setRunning(false);
      }
    },
    [],
  );

  return { running, progress, elapsed, result, error, start };
}

export function LiveProgressCard({
  title,
  steps,
  running,
  progress,
  elapsed,
  error,
  completeSummary,
}: {
  title: string;
  steps: ProgressStep[];
  running: boolean;
  progress: SseProgressEvent | null;
  elapsed: number;
  error: string | null;
  completeSummary?: string | null;
}) {
  if (!running && !error && !completeSummary) return null;

  const activeStepId = progress?.step ?? "";
  const activeIdx = steps.findIndex((s) => s.id === activeStepId);
  const hasKnownTotal =
    typeof progress?.completed === "number" &&
    typeof progress?.total === "number" &&
    progress.total > 0;
  const pct = hasKnownTotal
    ? Math.min(100, Math.round(((progress?.completed ?? 0) / (progress?.total ?? 1)) * 100))
    : null;

  return (
    <div className="mt-4 rounded-token-lg border border-border-strong bg-surface-raised p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-text-primary">
          {title}
        </span>
        <span className="tabular-nums font-mono text-xs text-text-muted">
          {running ? `${elapsed}s elapsed` : completeSummary ? "Completed" : "Stopped"}
        </span>
      </div>

      {steps.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {steps.map((step, idx) => {
            const done = !running && !error && Boolean(completeSummary);
            const past = activeIdx > idx;
            const current = running && activeIdx === idx;
            return (
              <span
                key={step.id}
                className={`rounded-token border px-2 py-0.5 text-[11px] font-medium ${
                  done || past
                    ? "border-stance-buy bg-stance-buy-soft text-stance-buy"
                    : current
                      ? "border-accent bg-accent-soft text-accent"
                      : "border-border-subtle bg-surface-sunken text-text-muted"
                }`}
              >
                {step.label}
              </span>
            );
          })}
        </div>
      ) : null}

      {running && progress ? (
        <div className="mt-3">
          <div className="flex items-baseline justify-between gap-2 text-xs">
            <span className="text-text-secondary">{progress.label}</span>
            {hasKnownTotal ? (
              <span className="tabular-nums font-mono text-text-primary">
                {progress.completed} / {progress.total} ({pct}%)
              </span>
            ) : null}
          </div>
          {pct !== null ? (
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
              <div
                className="h-full bg-accent transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {completeSummary && !running && !error ? (
        <p className="mt-2.5 text-xs font-medium text-stance-buy">{completeSummary}</p>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2.5 text-xs font-medium text-stance-avoid">
          {error}
        </p>
      ) : null}
    </div>
  );
}
