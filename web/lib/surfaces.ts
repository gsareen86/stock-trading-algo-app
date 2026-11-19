/**
 * Surfaces organised around the 10-minute daily ritual:
 * primary research & triage first, portfolio books & system observability second.
 */

export type SurfaceGroup = "research" | "portfolio";

export type Surface = {
  href: string;
  label: string;
  group: SurfaceGroup;
  /** The question this surface exists to answer. */
  answers: string;
};

export const SURFACES: Surface[] = [
  {
    href: "/",
    label: "Today",
    group: "research",
    answers: "Morning briefing & what needs my attention right now",
  },
  {
    href: "/ideas",
    label: "Ideas",
    group: "research",
    answers: "Sector rotation & Nifty 750 setups side by side",
  },
  {
    href: "/themes",
    label: "Themes",
    group: "research",
    answers: "What is emerging across supply chains, policy & concalls",
  },
  {
    href: "/watchlist",
    label: "Watchlist",
    group: "research",
    answers: "Tracked setups, pivot proximity & stance flips",
  },
  {
    href: "/stock",
    label: "Stock",
    group: "research",
    answers: "Everything known about one NSE name",
  },
  {
    href: "/positions",
    label: "Positions",
    group: "portfolio",
    answers: "What I own across both books & structural health",
  },
  {
    href: "/performance",
    label: "Performance",
    group: "portfolio",
    answers: "Realised vs unrealised P&L & alphabetical strategy attribution",
  },
  {
    href: "/broker",
    label: "Zerodha",
    group: "portfolio",
    answers: "Read-only mirror of real Kite holdings — never places orders",
  },
  {
    href: "/engine",
    label: "Engine",
    group: "portfolio",
    answers: "Models, 18 tools, scheduler & LLM cost ledger",
  },
];
