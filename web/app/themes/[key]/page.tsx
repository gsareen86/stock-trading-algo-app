import Link from "next/link";

import { RejectLink } from "@/components/reject-link";
import { Empty, Unavailable } from "@/components/states";
import { type ChainLink, type ThemeCandidate, fetchTheme } from "@/lib/api";

/**
 * One theme: what evidenced it, what it consumes, and who here is positioned for it.
 *
 * The chain is the part that needs care. Every tier was **proposed by a model**, and it is
 * displayed as such — reasoning visible in place, the model named, and a control to reject it.
 * A claim a reader cannot judge is one they cannot reject, and an unrejectable claim from a
 * model is exactly what this platform refuses to put in front of someone.
 */

export const dynamic = "force-dynamic";

const EXPOSURE_TONE: Record<string, string> = {
  established: "border-stance-buy text-stance-buy",
  claimed: "border-stance-watch text-stance-watch",
  unestablished: "border-border-strong text-text-muted",
};

/** What each grade actually means, in the words a reader needs rather than the enum's. */
const EXPOSURE_MEANS: Record<string, string> = {
  established: "its own business description names this activity",
  claimed: "management discussed it; nothing corroborates the scale",
  unestablished: "industry looked right; nothing corroborates it",
};

function CandidateRow({ candidate }: { candidate: ThemeCandidate }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border-subtle py-2.5 last:border-b-0">
      <div className="min-w-0">
        <Link
          href={`/stock?symbol=${encodeURIComponent(candidate.symbol)}`}
          className="font-mono text-sm text-accent underline"
        >
          {candidate.symbol}
        </Link>
        {candidate.exposure_basis ? (
          <p className="mt-0.5 text-xs text-text-muted">{candidate.exposure_basis}</p>
        ) : null}
      </div>
      <span
        className={`shrink-0 rounded-token border px-2 py-0.5 text-[11px] uppercase tracking-wider ${
          EXPOSURE_TONE[candidate.exposure] ?? ""
        }`}
        title={EXPOSURE_MEANS[candidate.exposure]}
      >
        {candidate.exposure}
      </span>
    </div>
  );
}

function Tier({
  link,
  candidates,
}: {
  link: ChainLink;
  candidates: ThemeCandidate[];
}) {
  return (
    <section
      className={`rounded-token-lg border p-5 ${
        link.rejected ? "border-border-subtle opacity-60" : "border-border-subtle bg-surface-raised"
      }`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-text-primary">
          Tier {link.tier} · {link.label}
        </h3>
        {link.rejected ? (
          <span className="text-[11px] uppercase tracking-wider text-text-muted">rejected</span>
        ) : null}
      </div>

      {link.supplies ? (
        <p className="mt-1 text-xs text-text-muted">supplies {link.supplies}</p>
      ) : null}

      {/* Reasoning in place, not behind a click. "Click through to see why" is a step people
          skip, and the whole argument for showing a model-proposed link depends on the why
          being cheap to reach. */}
      <p className="mt-3 text-sm text-text-secondary">{link.reasoning}</p>

      <p className="mt-2 text-[11px] text-text-muted">
        proposed by <span className="font-mono">{link.proposed_by}</span> — a proposal, not a
        measurement this platform made
      </p>

      {link.supplier_descriptions.length > 0 ? (
        <p className="mt-2 text-xs text-text-muted">
          suppliers: {link.supplier_descriptions.join(" · ")}
        </p>
      ) : null}

      <div className="mt-4">
        {candidates.length === 0 ? (
          <p className="text-xs text-text-muted">
            No company here matched on name or industry. This tier may still have Indian
            exposure that name matching cannot see.
          </p>
        ) : (
          candidates.map((candidate) => (
            <CandidateRow key={candidate.id} candidate={candidate} />
          ))
        )}
      </div>

      {!link.rejected ? (
        <div className="mt-4">
          <RejectLink linkId={link.id} label={link.label} />
        </div>
      ) : link.rejected_reason ? (
        <p className="mt-3 text-xs text-text-muted">reason: {link.rejected_reason}</p>
      ) : null}
    </section>
  );
}

export default async function ThemePage({
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
    <div className="mx-auto max-w-6xl px-6 py-10">
      <Link href="/themes" className="text-xs text-text-muted underline">
        ← Themes
      </Link>

      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary">
        {theme.label}
      </h1>
      <p className="mt-1 text-sm text-text-secondary">
        {theme.breadth} compan{theme.breadth === 1 ? "y" : "ies"} across {theme.sector_count}{" "}
        sector{theme.sector_count === 1 ? "" : "s"}, in {theme.persistence} period
        {theme.persistence === 1 ? "" : "s"} · from {theme.source_kinds.join(", ")}
      </p>

      {theme.withdrawn_at ? (
        <p className="mt-2 text-xs text-stance-watch">
          Withdrawn: {theme.withdrawal_reason}
        </p>
      ) : null}

      <section className="mt-8">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Supply chain
        </h2>
        <div className="mt-3 space-y-3">
          {theme.chain.length === 0 ? (
            <Empty>No chain has been expanded for this theme yet.</Empty>
          ) : (
            theme.chain.map((link) => (
              <Tier key={link.id} link={link} candidates={byTier.get(link.tier) ?? []} />
            ))
          )}
        </div>
      </section>

      <details className="mt-10">
        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-text-muted">
          What evidenced this ({theme.references.length})
        </summary>
        <div className="mt-3 space-y-2">
          {theme.references.map((reference) => (
            <div
              key={`${reference.symbol}-${reference.period}-${reference.source_ref}`}
              className="rounded-token border border-border-subtle bg-surface-sunken p-3"
            >
              <p className="text-xs text-text-secondary">
                <span className="font-mono">{reference.symbol}</span> · {reference.period} ·{" "}
                {reference.kind}
              </p>
              {reference.excerpt ? (
                <p className="mt-1 text-xs text-text-muted">“{reference.excerpt}”</p>
              ) : null}
              {/* Quoted from a document, never measured here — and a reader deciding what to
                  do with it needs to know which of the two they are reading. */}
              <p className="mt-1 text-[11px] text-stance-watch">
                quoted from a document, not measured by this platform
              </p>
            </div>
          ))}
        </div>
      </details>

      <p className="mt-10 text-xs text-text-muted">
        A theme is a lens, not a verdict. Nothing here carries a stance or a conviction —
        follow any candidate to see what the four strategies say about it.
      </p>
    </div>
  );
}
