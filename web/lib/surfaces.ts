/**
 * The six surfaces, organised by intent rather than by internal module.
 *
 * The predecessor had twelve pages mirroring its own package layout, which meant
 * finding anything required knowing how the code was structured. These are named
 * for the question each one answers.
 */

export type Surface = {
  href: string;
  label: string;
  /** The question this surface exists to answer. */
  answers: string;
  /** OpenSpec change that fills it in with real content. */
  filledBy: string;
};

export const SURFACES: Surface[] = [
  {
    href: "/",
    label: "Today",
    answers: "What needs my attention right now",
    filledBy: "insights-feed",
  },
  {
    href: "/ideas",
    label: "Ideas",
    answers: "What could I buy — every strategy's verdict, side by side",
    filledBy: "gui-surfaces",
  },
  {
    href: "/positions",
    label: "Positions",
    answers: "What do I own, across both books",
    filledBy: "books-ledger-and-analytics",
  },
  {
    href: "/stock",
    label: "Stock",
    answers: "Everything known about one name",
    filledBy: "gui-surfaces",
  },
  {
    href: "/performance",
    label: "Performance",
    answers: "How am I doing — by book, by strategy, vs benchmark",
    filledBy: "books-ledger-and-analytics",
  },
  {
    href: "/engine",
    label: "Engine",
    answers: "Under the hood — config, runs, agent traces, LLM cost",
    filledBy: "agent-graph-and-a2a",
  },
];
