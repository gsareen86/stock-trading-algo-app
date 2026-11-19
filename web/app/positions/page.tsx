import { PositionsBoard } from "@/components/positions-board";
import { fetchBookHealth, fetchPositions } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PositionsPage() {
  const [swingPos, swingHealth, ltPos, ltHealth] = await Promise.all([
    fetchPositions("swing"),
    fetchBookHealth("swing"),
    fetchPositions("longterm"),
    fetchBookHealth("longterm"),
  ]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <PositionsBoard
        books={[
          { book: "swing", label: "Swing", positions: swingPos, health: swingHealth },
          { book: "longterm", label: "Long-Term", positions: ltPos, health: ltHealth },
        ]}
      />
    </div>
  );
}
