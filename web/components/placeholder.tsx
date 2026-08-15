import { SURFACES } from "@/lib/surfaces";

/**
 * A surface whose real content lands in a later change.
 *
 * It names the change that will fill it and shows no trading data at all. Plausible-looking
 * fake numbers on a trading screen are worse than an empty one — they are indistinguishable
 * from real output at a glance, and this platform's whole premise is that every figure on
 * screen traces back to evidence.
 */
export function Placeholder({ href }: { href: string }) {
  const surface = SURFACES.find((item) => item.href === href);
  if (!surface) return null;

  return (
    <section className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-text-primary">
        {surface.label}
      </h1>
      <p className="mt-1 text-sm text-text-secondary">{surface.answers}</p>

      <div className="mt-8 rounded-token-lg border border-dashed border-border-strong bg-surface-sunken px-6 py-10 text-center">
        <p className="text-sm font-medium text-text-primary">
          Not built yet — this is the navigation shell
        </p>
        <p className="mx-auto mt-2 max-w-md text-sm text-text-secondary">
          Real content arrives with the{" "}
          <code className="rounded-token bg-surface-raised px-1.5 py-0.5 font-mono text-xs text-accent">
            {surface.filledBy}
          </code>{" "}
          change. Nothing is shown here rather than showing numbers that aren&apos;t real.
        </p>
      </div>
    </section>
  );
}
