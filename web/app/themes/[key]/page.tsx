import Link from "next/link";

import { RejectLink } from "@/components/reject-link";
import { Empty, Unavailable } from "@/components/states";
import { type ChainLink, type ThemeCandidate, fetchTheme } from "@/lib/api";

export const dynamic = "force-dynamic";

const EXPOSURE_TONE: Record<string, string> = {
  established: "border-stance-buy bg-stance-buy-soft text-stance-buy",
  claimed: "border-stance-watch bg-stance-watch-soft text-stance-watch",
  unestablished: "border-border-strong bg-surface-sunken text-text-muted",
};

const EXPOSURE_MEANS: Record<string, string> = {
  established: "its own business description names this activity",
  claimed: "management discussed it; nothing corroborates the scale",
  unestablished: "industry looked right; nothing corroborates it",
};

function CandidateRow({ candidate }: { candidate: ThemeCandidate }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border-subtle py-2.5 last:border-b-0">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/stock?symbol=${encodeURIComponent(candidate.symbol)}`}
            className="font-mono text-sm font-semibold text-accent hover:underline"
          >
            {candidate.symbol} →
          </Link>
          {candidate.matched_description ? (
            <span className="text-xs text-text-secondary">
              {candidate.matched_description}
            </span>
          ) : null}
        </div>
        {candidate.exposure_basis ? (
          <p className="mt-0.5 text-xs text-text-muted">{candidate.exposure_basis}</p>
        ) : null}
      </div>
      <span
        className={`shrink-0 rounded-token border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
          EXPOSURE_TONE[candidate.exposure] ?? ""
        }`}
        title={EXPOSURE_MEANS[candidate.exposure]}
      >
        {candidate.exposure}
      </span>
    </div>
  );
}

function TierCard({
  link,
  candidates,
}: {
  link: ChainLink;
  candidates: ThemeCandidate[];
}) {
  return (
    <section
      className={`card-surface p-5 ${link.rejected ? "opacity-60" : ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <span className="rounded-token bg-accent-soft px-2 py-0.5 font-mono text-[11px] font-semibold text-accent">
            Tier {link.tier}
          </span>
          <h3 className="mt-1.5 text-base font-semibold text-text-primary">
            {link.label}
          </h3>
          {link.supplies ? (
            <p className="mt-0.5 text-xs text-text-muted">Supplies → {link.supplies}</p>
          ) : null}
        </div>

        {link.rejected ? (
          <span className="rounded-token border border-border-subtle bg-surface-sunken px-2 py-0.5 text-[11px] uppercase tracking-wider text-text-muted">
            Rejected
          </span>
        ) : (
          <RejectLink linkId={link.id} label={link.label} />
        )}
      </div>

      <p className="mt-3 text-sm leading-relaxed text-text-secondary">{link.reasoning}</p>

      <p className="mt-2 rounded-token bg-surface-sunken px-2.5 py-1.5 text-[11px] text-text-muted">
        Proposed by <span className="font-mono text-text-primary">{link.proposed_by}</span> —
        reviewable AI proposal, not a measurement by this platform
      </p>

      {link.supplier_descriptions.length > 0 ? (
        <p className="mt-2 text-xs text-text-muted">
          Matched profiles: {link.supplier_descriptions.join(" · ")}
        </p>
      ) : null}

      <div className="mt-4 border-t border-border-subtle pt-3">
        {candidates.length === 0 ? (
          <p className="text-xs text-text-muted">
            No company matched on name or business description. This tier may still hold NSE exposure that keyword matching did not resolve.
          </p>
        ) : (
          candidates.map((candidate) => (
            <CandidateRow key={candidate.id} candidate={candidate} />
          ))
        )}
      </div>

      {link.rejected && link.rejected_reason ? (
        <p className="mt-3 text-xs text-text-muted">Rejection reason: {link.rejected_reason}</p>
      ) : null}
    </section>
  );
}

export default async function ThemeDetailPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const { key } = await params;
  const result = await fetchTheme(key);

  if (!result.ok) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-10">
        <Unavailable result={result} />
      </div>
    );
  }

  const theme = result.data;
  const byTier = new Map<number, ThemeCandidate[]>();
  for (const candidate of theme.candidates) {
    byTier.set(candidate.tier, [...(byTier.get(candidate.tier) ?? []), candidate]);
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-6 py-8">
      <section className="hero-surface p-6">
        <Link href="/themes" className="text-xs font-medium text-accent hover:underline">
          ← All Themes
        </Link>

        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
              {theme.label}
            </h1>
            <p className="mt-1 text-sm text-text-secondary">
              Sources: {theme.source_kinds.join(", ") || "none"} · first seen{" "}
              {theme.first_seen_at ? theme.first_seen_at.slice(0, 10) : "—"}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <span className="tabular-nums rounded-token border border-border-subtle bg-surface-raised px-3 py-1.5 font-mono text-xs font-semibold text-text-primary">
              {theme.breadth} companies
            </span>
            <span className="tabular-nums rounded-token border border-border-subtle bg-surface-raised px-3 py-1.5 font-mono text-xs font-semibold text-text-primary">
              {theme.sector_count} sectors
            </span>
            <span className="tabular-nums rounded-token border border-border-subtle bg-surface-raised px-3 py-1.5 font-mono text-xs font-semibold text-text-primary">
              {theme.persistence} periods
            </span>
          </div>
        </div>

        {theme.withdrawn_at ? (
          <p className="mt-3 rounded-token bg-stance-watch-soft px-3 py-2 text-xs font-medium text-stance-watch">
            Withdrawn: {theme.withdrawal_reason}
          </p>
        ) : null}
      </section>

      <section className="space-y-4">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Supply-Chain Tier Flow
        </h2>

        {theme.chain.length === 0 ? (
          <Empty>No supply-chain tiers have been expanded for this theme yet.</Empty>
        ) : (
          <div className="space-y-4">
            {theme.chain.map((link) => (
              <TierCard
                key={link.id}
                link={link}
                candidates={byTier.get(link.tier) ?? []}
              />
            ))}
          </div>
        )}
      </section>

      <details className="card-surface p-5">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-text-muted">
          Source Excerpts &amp; Evidence ({theme.references.length})
        </summary>
        <div className="mt-4 space-y-2.5">
          {theme.references.map((reference) => (
            <div
              key={`${reference.symbol}-${reference.period}-${reference.source_ref}`}
              className="rounded-token border border-border-subtle bg-surface-sunken p-3"
            >
              <p className="text-xs text-text-secondary">
                <span className="font-mono font-semibold text-text-primary">
                  {reference.symbol}
                </span>{" "}
                · {reference.period} · {reference.kind}
              </p>
              {reference.excerpt ? (
                <p className="mt-1 text-xs text-text-secondary">&ldquo;{reference.excerpt}&rdquo;</p>
              ) : null}
              <p className="mt-1 text-[11px] text-stance-watch">
                Quoted from a document, not measured by this platform
              </p>
            </div>
          ))}
        </div>
      </details>

      <p className="text-xs text-text-muted">
        A theme is a lens, not a verdict. Nothing here carries a stance or a conviction — click any symbol above to inspect what all four independent strategies conclude.
      </p>
    </div>
  );
}
