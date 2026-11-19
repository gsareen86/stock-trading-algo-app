import { Unavailable } from "@/components/states";
import { WatchlistBoard } from "@/components/watchlist-board";
import { fetchWatchlist } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function WatchlistPage() {
  const result = await fetchWatchlist();

  if (!result.ok) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-10">
        <Unavailable result={result} />
      </div>
    );
  }

  const boardKey = result.data.items.map((i) => `${i.symbol}:${i.updated_at}`).join(",");

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <WatchlistBoard key={boardKey} initialItems={result.data.items} />
    </div>
  );
}
