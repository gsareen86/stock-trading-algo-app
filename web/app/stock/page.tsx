import { StockLookupHero, StockWorkstation } from "@/components/stock-workstation";
import { Unavailable } from "@/components/states";
import {
  evaluate,
  fetchLatestDiscovery,
  fetchPositions,
  fetchStockChart,
  fetchStockQuality,
  fetchStockResearch,
  fetchWatchlist,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function StockPage({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string }>;
}) {
  const params = await searchParams;
  const rawSymbol = (params.symbol ?? "").trim().toUpperCase();

  if (!rawSymbol) {
    const [watchlistRes, latestRes] = await Promise.all([
      fetchWatchlist(),
      fetchLatestDiscovery({ limit: 8 }),
    ]);

    const picks: { symbol: string; tag: string }[] = [];
    const seen = new Set<string>();
    if (watchlistRes.ok) {
      for (const item of watchlistRes.data.items.slice(0, 4)) {
        if (!seen.has(item.symbol)) {
          seen.add(item.symbol);
          picks.push({
            symbol: item.symbol,
            tag: item.flipped_buy ? "WATCH → BUY" : "Watchlist",
          });
        }
      }
    }
    if (latestRes.ok) {
      for (const c of latestRes.data.candidates.slice(0, 6)) {
        if (!seen.has(c.symbol)) {
          seen.add(c.symbol);
          picks.push({ symbol: c.symbol, tag: c.ranked_by });
        }
      }
    }

    return <StockLookupHero quickPicks={picks.slice(0, 8)} />;
  }

  const [verdictRes, chartRes, qualityRes, researchRes, swingRes, longtermRes, watchlistRes] =
    await Promise.all([
      evaluate([rawSymbol], true),
      fetchStockChart(rawSymbol, "1Y"),
      fetchStockQuality(rawSymbol),
      fetchStockResearch(rawSymbol, false),
      fetchPositions("swing"),
      fetchPositions("longterm"),
      fetchWatchlist(),
    ]);

  if (!verdictRes.ok && !chartRes.ok) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-10">
        <Unavailable result={verdictRes} />
      </div>
    );
  }

  const heldPositions = [
    ...(swingRes.ok ? swingRes.data.positions : []),
    ...(longtermRes.ok ? longtermRes.data.positions : []),
  ].filter((p) => p.ticker === rawSymbol);

  const initiallyWatched = watchlistRes.ok
    ? watchlistRes.data.items.some((w) => w.symbol === rawSymbol)
    : false;

  return (
    <StockWorkstation
      key={rawSymbol}
      symbol={rawSymbol}
      verdicts={verdictRes.ok ? verdictRes.data.verdicts : []}
      chart={chartRes.ok ? chartRes.data : null}
      quality={qualityRes.ok ? qualityRes.data : null}
      initialResearch={researchRes.ok ? researchRes.data : null}
      heldPositions={heldPositions}
      initiallyWatched={initiallyWatched}
    />
  );
}
