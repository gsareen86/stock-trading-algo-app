"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import type { UniverseSymbol } from "@/lib/api";
import { SURFACES } from "@/lib/surfaces";

const RECENT_KEY = "sw_recent_symbols";

function loadRecent(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string").slice(0, 5) : [];
  } catch {
    return [];
  }
}

export function rememberSymbol(symbol: string) {
  if (typeof window === "undefined") return;
  try {
    const clean = symbol.trim().toUpperCase();
    const prev = loadRecent().filter((s) => s !== clean);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify([clean, ...prev].slice(0, 5)));
  } catch {
    // Ignore storage quota / privacy mode errors.
  }
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [symbols, setSymbols] = useState<UniverseSymbol[]>([]);
  const [loading, setLoading] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const openPalette = useMemo(
    () => () => {
      setRecent(loadRecent());
      setQuery("");
      setActiveIndex(0);
      setOpen(true);
      window.setTimeout(() => inputRef.current?.focus(), 10);
      if (symbols.length === 0 && !loading) {
        setLoading(true);
        fetch("/api/backend/universe/symbols?limit=750")
          .then((res) => (res.ok ? res.json() : null))
          .then((data) => {
            if (data && Array.isArray(data.symbols)) {
              setSymbols(data.symbols);
            }
          })
          .catch(() => {})
          .finally(() => setLoading(false));
      }
    },
    [symbols.length, loading],
  );

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (open) setOpen(false);
        else openPalette();
      } else if (
        e.key === "/" &&
        !open &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement) &&
        !(e.target instanceof HTMLSelectElement)
      ) {
        e.preventDefault();
        openPalette();
      } else if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    }
    function onCustomOpen() {
      openPalette();
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("open-command-palette", onCustomOpen);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("open-command-palette", onCustomOpen);
    };
  }, [open, openPalette]);

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) {
      return symbols.slice(0, 8);
    }
    const exactPrefix: UniverseSymbol[] = [];
    const contains: UniverseSymbol[] = [];
    for (const item of symbols) {
      const sym = item.symbol.toUpperCase();
      const name = (item.name ?? "").toUpperCase();
      if (sym.startsWith(q)) {
        exactPrefix.push(item);
      } else if (sym.includes(q) || name.includes(q)) {
        contains.push(item);
      }
      if (exactPrefix.length + contains.length >= 12) break;
    }
    return [...exactPrefix, ...contains].slice(0, 10);
  }, [query, symbols]);

  const surfaceMatches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return SURFACES.slice(0, 5);
    return SURFACES.filter(
      (s) => s.label.toLowerCase().includes(q) || s.answers.toLowerCase().includes(q),
    );
  }, [query]);

  function goToSymbol(symbol: string) {
    rememberSymbol(symbol);
    setOpen(false);
    router.push(`/stock?symbol=${encodeURIComponent(symbol.toUpperCase())}`);
  }

  function goToSurface(href: string) {
    setOpen(false);
    router.push(href);
  }

  if (!open) return null;

  const totalOptions = matches.length + surfaceMatches.length;

  function onInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) => (totalOptions > 0 ? (prev + 1) % totalOptions : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) =>
        totalOptions > 0 ? (prev - 1 + totalOptions) % totalOptions : 0,
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIndex < matches.length && matches[activeIndex]) {
        goToSymbol(matches[activeIndex].symbol);
      } else if (surfaceMatches[activeIndex - matches.length]) {
        goToSurface(surfaceMatches[activeIndex - matches.length].href);
      } else if (query.trim().length >= 2) {
        goToSymbol(query.trim().toUpperCase());
      }
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Global stock and surface lookup"
      className="fixed inset-0 z-50 flex items-start justify-center bg-text-primary/30 px-4 pt-20 backdrop-blur-xs"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-token-xl border border-border-strong bg-surface-elevated shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-border-subtle px-4 py-3">
          <span className="font-mono text-xs text-text-muted">⌘K</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={onInputKeyDown}
            placeholder="Search any NSE Nifty 750 ticker, company, or workspace..."
            className="w-full bg-transparent text-sm text-text-primary outline-none placeholder:text-text-muted"
          />
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-token border border-border-subtle px-1.5 py-0.5 font-mono text-[11px] text-text-muted hover:text-text-primary"
          >
            ESC
          </button>
        </div>

        <div className="max-h-[26rem] overflow-y-auto p-3">
          {!query.trim() && recent.length > 0 ? (
            <div className="mb-3">
              <p className="px-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                Recent stocks
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5 px-2">
                {recent.map((sym) => (
                  <button
                    key={sym}
                    type="button"
                    onClick={() => goToSymbol(sym)}
                    className="rounded-token border border-border-subtle bg-surface-sunken px-2.5 py-1 font-mono text-xs text-text-primary transition-colors hover:border-accent hover:text-accent"
                  >
                    {sym}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <div>
            <div className="flex items-center justify-between px-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                NSE Nifty Total Market {symbols.length > 0 ? `(${symbols.length})` : ""}
              </p>
              {loading ? <span className="text-[11px] text-text-muted">Loading…</span> : null}
            </div>

            {matches.length === 0 && !loading ? (
              <div className="mt-2 px-2 py-2 text-xs text-text-muted">
                {query.trim().length >= 2 ? (
                  <button
                    type="button"
                    onClick={() => goToSymbol(query.trim().toUpperCase())}
                    className="text-accent underline"
                  >
                    Open deep-dive for &ldquo;{query.trim().toUpperCase()}&rdquo; →
                  </button>
                ) : (
                  "No matching NSE tickers."
                )}
              </div>
            ) : (
              <ul className="mt-1 space-y-0.5">
                {matches.map((item, idx) => {
                  const selected = idx === activeIndex;
                  return (
                    <li key={item.symbol}>
                      <button
                        type="button"
                        onClick={() => goToSymbol(item.symbol)}
                        className={`flex w-full items-center justify-between rounded-token px-2.5 py-2 text-left text-sm transition-colors ${
                          selected
                            ? "bg-accent-soft text-accent"
                            : "text-text-primary hover:bg-surface-sunken"
                        }`}
                      >
                        <div className="min-w-0 truncate">
                          <span className="font-mono font-semibold">{item.symbol}</span>
                          <span className="ml-2.5 text-xs text-text-secondary">
                            {item.name}
                          </span>
                        </div>
                        {item.sector ? (
                          <span className="ml-2 shrink-0 rounded-token bg-surface-sunken px-2 py-0.5 text-[11px] text-text-muted">
                            {item.sector}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {surfaceMatches.length > 0 ? (
            <div className="mt-4 border-t border-border-subtle pt-3">
              <p className="px-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
                Surfaces
              </p>
              <ul className="mt-1 space-y-0.5">
                {surfaceMatches.map((surface, idx) => {
                  const selected = matches.length + idx === activeIndex;
                  return (
                    <li key={surface.href}>
                      <button
                        type="button"
                        onClick={() => goToSurface(surface.href)}
                        className={`flex w-full items-center justify-between rounded-token px-2.5 py-1.5 text-left text-sm transition-colors ${
                          selected
                            ? "bg-accent-soft text-accent"
                            : "text-text-secondary hover:bg-surface-sunken hover:text-text-primary"
                        }`}
                      >
                        <span className="font-medium text-text-primary">{surface.label}</span>
                        <span className="truncate pl-3 text-xs text-text-muted">
                          {surface.answers}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
