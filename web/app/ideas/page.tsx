import { IdeasExplorer } from "@/components/ideas-explorer";
import { Unavailable } from "@/components/states";
import {
  fetchBriefing,
  fetchDiscoverySectors,
  fetchLatestDiscovery,
  fetchWatchlist,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function IdeasPage() {
  const [latestRes, sectorsRes, watchlistRes, briefingRes] = await Promise.all([
    fetchLatestDiscovery({ limit: 200 }),
    fetchDiscoverySectors("^CRSLDX"),
    fetchWatchlist(),
    fetchBriefing(),
  ]);

  if (!latestRes.ok && !sectorsRes.ok) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-10">
        <Unavailable result={latestRes} />
      </div>
    );
  }

  const sectors = sectorsRes.ok
    ? sectorsRes.data.sectors
    : latestRes.ok
      ? latestRes.data.sectors
      : [];
  const watched = watchlistRes.ok ? watchlistRes.data.items.map((w) => w.symbol) : [];

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <IdeasExplorer
        initialLatest={latestRes.ok ? latestRes.data : null}
        initialSectors={sectors}
        initialWatchedSymbols={watched}
        nifty50={briefingRes.ok ? briefingRes.data.market.nifty50 : undefined}
        nifty500={briefingRes.ok ? briefingRes.data.market.nifty500 : undefined}
      />
    </div>
  );
}
