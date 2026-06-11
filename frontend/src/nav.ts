/* Tiny cross-page navigation store: lets any page jump to another page with a
   ticker pre-filled (e.g. Swing scan row → Research / News / Fundamentals). */

let _go: ((page: string) => void) | null = null;
let _pendingTicker: string | null = null;

export function bindNavigator(fn: (page: string) => void) {
  _go = fn;
}

/** Navigate to a page with a ticker context the target page can consume. */
export function goToTicker(page: string, ticker: string) {
  _pendingTicker = (ticker || "").split(".")[0].toUpperCase();
  _go?.(page);
}

/** Called once by the target page on mount — returns and clears the ticker. */
export function takeTicker(): string {
  const t = _pendingTicker ?? "";
  _pendingTicker = null;
  return t;
}
