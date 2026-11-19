"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { InsightActions } from "@/components/insight-actions";
import { Empty, Unavailable } from "@/components/states";
import type { Fetched, Insight } from "@/lib/api";

type FilterBucket = "all" | "watchlist" | "sectors" | "themes" | "unread";

const SEVERITY_ACCENT: Record<string, string> = {
  high: "border-l-4 border-l-stance-avoid",
  medium: "border-l-4 border-l-stance-watch",
  low: "border-l-4 border-l-border-strong",
};

const SEVERITY_BADGE: Record<string, string> = {
  high: "border-stance-avoid bg-stance-avoid-soft text-stance-avoid",
  medium: "border-stance-watch bg-stance-watch-soft text-stance-watch",
  low: "border-border-subtle bg-surface-sunken text-text-muted",
};

function measuredAgo(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function TodayInsights({
  feed,
}: {
  feed: Fetched<{ insights: Insight[]; unread: number }>;
}) {
  const router = useRouter();
  const [bucket, setBucket] = useState<FilterBucket>("all");
  const [markingAll, setMarkingAll] = useState(false);

  const items = useMemo(() => (feed.ok ? feed.data.insights : []), [feed]);

  const filtered = useMemo(() => {
    if (bucket === "all") return items;
    if (bucket === "unread") return items.filter((i) => !i.read);
    if (bucket === "watchlist") {
      return items.filter(
        (i) =>
          i.kind.includes("watchlist") ||
          i.kind.includes("thesis") ||
          i.kind.includes("concentration") ||
          i.kind.includes("flip"),
      );
    }
    if (bucket === "sectors") return items.filter((i) => i.kind.includes("sector"));
    if (bucket === "themes") {
      return items.filter((i) => i.kind.includes("theme") || i.kind.includes("concall"));
    }
    return items;
  }, [items, bucket]);

  async function markAllRead() {
    setMarkingAll(true);
    try {
      const res = await fetch("/api/backend/insights/read-all", { method: "POST" });
      if (res.ok) router.refresh();
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {(
            [
              { id: "all", label: "All" },
              { id: "unread", label: `Unread${feed.ok ? ` (${feed.data.unread})` : ""}` },
              { id: "watchlist", label: "Watchlist & Holdings" },
              { id: "sectors", label: "Sector Shifts" },
              { id: "themes", label: "Themes & Concalls" },
            ] as const
          ).map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setBucket(tab.id)}
              className={`rounded-token border px-2.5 py-1 text-xs font-medium transition-colors ${
                bucket === tab.id
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-border-subtle bg-surface-raised text-text-secondary hover:text-text-primary"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {feed.ok && feed.data.unread > 0 ? (
          <button
            type="button"
            disabled={markingAll}
            onClick={markAllRead}
            className="text-xs font-medium text-text-muted hover:text-text-primary disabled:opacity-50"
          >
            {markingAll ? "Marking…" : "Mark all read"}
          </button>
        ) : null}
      </div>

      <div className="mt-4">
        {!feed.ok ? (
          <Unavailable result={feed} />
        ) : filtered.length === 0 ? (
          <Empty>
            {items.length === 0
              ? "Nothing needs attention right now. Run a daily scan or full cycle above."
              : "No insights match this filter."}
          </Empty>
        ) : (
          <div className="space-y-3">
            {filtered.map((insight) => (
              <article
                key={insight.id}
                className={`card-surface p-4 ${SEVERITY_ACCENT[insight.severity] ?? ""} ${
                  insight.read ? "opacity-70" : ""
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      {insight.ticker ? (
                        <Link
                          href={`/stock?symbol=${encodeURIComponent(insight.ticker)}`}
                          className="rounded-token bg-surface-sunken px-2 py-0.5 font-mono text-xs font-semibold text-accent hover:underline"
                        >
                          {insight.ticker}
                        </Link>
                      ) : null}
                      <h3 className="text-sm font-semibold text-text-primary">{insight.title}</h3>
                    </div>
                  </div>
                  <span
                    className={`shrink-0 rounded-token border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                      SEVERITY_BADGE[insight.severity] ?? ""
                    }`}
                  >
                    {insight.severity}
                  </span>
                </div>

                {insight.body ? (
                  <p className="mt-2 text-sm text-text-secondary">{insight.body}</p>
                ) : null}

                <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11px] text-text-muted">
                  <span className="font-mono">{insight.kind}</span>
                  {insight.measured_at ? (
                    <span>· measured {measuredAgo(insight.measured_at)}</span>
                  ) : null}
                  {insight.payload?.measured_by_platform === false ? (
                    <span className="rounded-token bg-stance-watch-soft px-1.5 py-0.5 font-medium text-stance-watch">
                      Tool-Reported — verify source
                    </span>
                  ) : (
                    <span className="rounded-token bg-surface-sunken px-1.5 py-0.5 text-text-muted">
                      Measured by Platform
                    </span>
                  )}
                  {insight.ticker ? (
                    <Link
                      href={`/stock?symbol=${encodeURIComponent(insight.ticker)}`}
                      className="ml-auto font-medium text-accent hover:underline"
                    >
                      Inspect {insight.ticker} →
                    </Link>
                  ) : null}
                </div>

                {!insight.read && insight.actions.length > 0 ? (
                  <InsightActions insight={insight} />
                ) : null}
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
