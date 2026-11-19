"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SURFACES } from "@/lib/surfaces";

export function Nav() {
  const pathname = usePathname();
  const research = SURFACES.filter((s) => s.group === "research");
  const portfolio = SURFACES.filter((s) => s.group === "portfolio");

  function renderLink(surface: (typeof SURFACES)[number]) {
    const active =
      surface.href === "/" ? pathname === "/" : pathname.startsWith(surface.href);
    return (
      <li key={surface.href}>
        <Link
          href={surface.href}
          aria-current={active ? "page" : undefined}
          title={surface.answers}
          className={
            active
              ? "block rounded-token bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent sm:text-sm"
              : "block rounded-token px-2.5 py-1 text-xs font-medium text-text-secondary transition-colors hover:bg-surface-sunken hover:text-text-primary sm:text-sm"
          }
        >
          {surface.label}
        </Link>
      </li>
    );
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border-subtle bg-surface-raised/95 backdrop-blur-xs">
      <div className="mx-auto flex max-w-6xl flex-col gap-2.5 px-6 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Link
              href="/"
              className="flex h-6 w-6 items-center justify-center rounded-token bg-accent text-[11px] font-bold tracking-tight text-surface-raised"
            >
              SL
            </Link>
            <Link
              href="/"
              className="text-sm font-semibold tracking-tight text-text-primary"
            >
              Swing &amp; Long-Term
            </Link>
            <span className="rounded-token border border-border-subtle bg-surface-sunken px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
              Paper only
            </span>
          </div>

          <button
            type="button"
            onClick={() => window.dispatchEvent(new Event("open-command-palette"))}
            className="flex w-full items-center justify-between gap-3 rounded-token border border-border-subtle bg-surface-sunken px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong hover:text-text-primary sm:w-64"
          >
            <span>Jump to NSE 750 stock…</span>
            <kbd className="rounded-token border border-border-subtle bg-surface-raised px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
              ⌘K
            </kbd>
          </button>
        </div>

        <nav aria-label="Surfaces" className="flex flex-wrap items-center gap-y-1.5">
          <ul className="flex flex-wrap items-center gap-1">
            {research.map(renderLink)}
          </ul>
          <span
            aria-hidden
            className="mx-2 hidden h-4 w-px bg-border-subtle sm:inline-block"
          />
          <ul className="flex flex-wrap items-center gap-1">
            {portfolio.map(renderLink)}
          </ul>
        </nav>
      </div>
    </header>
  );
}
