"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SURFACES } from "@/lib/surfaces";

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-border-subtle bg-surface-raised">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-6 py-4">
        <div className="flex items-baseline gap-3">
          <span className="text-sm font-semibold tracking-tight text-text-primary">
            Swing &amp; Long-Term
          </span>
          <span className="rounded-token border border-border-subtle px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-text-muted">
            Paper only
          </span>
        </div>

        <nav aria-label="Surfaces">
          <ul className="flex flex-wrap gap-1">
            {SURFACES.map((surface) => {
              // "/" would prefix-match everything, so it has to match exactly.
              const active =
                surface.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(surface.href);

              return (
                <li key={surface.href}>
                  <Link
                    href={surface.href}
                    aria-current={active ? "page" : undefined}
                    title={surface.answers}
                    className={
                      active
                        ? "block rounded-token bg-accent-soft px-3 py-1.5 text-sm font-medium text-accent"
                        : "block rounded-token px-3 py-1.5 text-sm text-text-secondary transition-colors hover:bg-surface-sunken hover:text-text-primary"
                    }
                  >
                    {surface.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
