"use client";

import { useState } from "react";

import type { SectorPlacement } from "@/lib/api";

const QUADRANT_COLOR: Record<string, string> = {
  Leading: "var(--quadrant-leading)",
  Improving: "var(--quadrant-improving)",
  Weakening: "var(--quadrant-weakening)",
  Lagging: "var(--quadrant-lagging)",
};

const QUADRANT_SOFT: Record<string, string> = {
  Leading: "var(--quadrant-leading-soft)",
  Improving: "var(--quadrant-improving-soft)",
  Weakening: "var(--quadrant-weakening-soft)",
  Lagging: "var(--quadrant-lagging-soft)",
};

function clampCoord(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val));
}

export function SectorRrgPlot({
  sectors,
  selectedSectorKey,
  onSelectSector,
}: {
  sectors: SectorPlacement[];
  selectedSectorKey: string | null;
  onSelectSector: (sectorKey: string | null) => void;
}) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const placed = sectors.filter(
    (s) =>
      s.quadrant !== "unplaced" &&
      typeof s.rs_ratio === "number" &&
      typeof s.rs_momentum === "number",
  );
  const unplaced = sectors.filter((s) => s.quadrant === "unplaced");

  // Dynamic symmetric bounds around 100 so points remain readable without clipping
  const maxOffset = placed.reduce((acc, s) => {
    const dx = Math.abs((s.rs_ratio ?? 100) - 100);
    const dy = Math.abs((s.rs_momentum ?? 100) - 100);
    return Math.max(acc, dx, dy);
  }, 4);
  const span = Math.max(5, Math.ceil(maxOffset * 1.2));
  const W = 560;
  const H = 340;
  const PAD = 32;

  const toX = (rsRatio: number) =>
    PAD + ((clampCoord(rsRatio, 100 - span, 100 + span) - (100 - span)) / (2 * span)) * (W - PAD * 2);
  const toY = (rsMom: number) =>
    H - PAD - ((clampCoord(rsMom, 100 - span, 100 + span) - (100 - span)) / (2 * span)) * (H - PAD * 2);

  const midX = toX(100);
  const midY = toY(100);
  const activeKey = hoveredKey ?? selectedSectorKey;

  return (
    <div className="card-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
            NSE Sector Relative Rotation (RRG)
          </h2>
          <p className="mt-0.5 text-xs text-text-secondary">
            Click any sector node or quadrant to isolate setups below
          </p>
        </div>
        {selectedSectorKey ? (
          <button
            type="button"
            onClick={() => onSelectSector(null)}
            className="rounded-token border border-border-subtle bg-surface-sunken px-2.5 py-1 text-xs font-medium text-text-primary hover:border-border-strong"
          >
            Clear sector filter ×
          </button>
        ) : null}
      </div>

      <div className="mt-3 overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="h-auto w-full min-w-[420px] select-none rounded-token-lg border border-border-subtle"
          role="img"
          aria-label="Four-quadrant sector rotation plot"
        >
          {/* Four shaded quadrant backgrounds */}
          <rect
            x={PAD}
            y={PAD}
            width={midX - PAD}
            height={midY - PAD}
            fill={QUADRANT_SOFT.Improving}
            opacity={0.55}
          />
          <rect
            x={midX}
            y={PAD}
            width={W - PAD - midX}
            height={midY - PAD}
            fill={QUADRANT_SOFT.Leading}
            opacity={0.55}
          />
          <rect
            x={PAD}
            y={midY}
            width={midX - PAD}
            height={H - PAD - midY}
            fill={QUADRANT_SOFT.Lagging}
            opacity={0.55}
          />
          <rect
            x={midX}
            y={midY}
            width={W - PAD - midX}
            height={H - PAD - midY}
            fill={QUADRANT_SOFT.Weakening}
            opacity={0.55}
          />

          {/* Center crosshairs at 100, 100 */}
          <line
            x1={midX}
            y1={PAD}
            x2={midX}
            y2={H - PAD}
            stroke="var(--border-strong)"
            strokeDasharray="4 4"
          />
          <line
            x1={PAD}
            y1={midY}
            x2={W - PAD}
            y2={midY}
            stroke="var(--border-strong)"
            strokeDasharray="4 4"
          />

          {/* Quadrant corner labels */}
          <text x={PAD + 10} y={PAD + 18} fontSize="11" fontWeight="600" fill={QUADRANT_COLOR.Improving}>
            IMPROVING
          </text>
          <text
            x={W - PAD - 10}
            y={PAD + 18}
            textAnchor="end"
            fontSize="11"
            fontWeight="600"
            fill={QUADRANT_COLOR.Leading}
          >
            LEADING
          </text>
          <text
            x={PAD + 10}
            y={H - PAD - 10}
            fontSize="11"
            fontWeight="600"
            fill={QUADRANT_COLOR.Lagging}
          >
            LAGGING
          </text>
          <text
            x={W - PAD - 10}
            y={H - PAD - 10}
            textAnchor="end"
            fontSize="11"
            fontWeight="600"
            fill={QUADRANT_COLOR.Weakening}
          >
            WEAKENING
          </text>

          {/* Trails + sector nodes */}
          {placed.map((sector) => {
            const x = toX(sector.rs_ratio ?? 100);
            const y = toY(sector.rs_momentum ?? 100);
            const isSelected = selectedSectorKey === sector.key;
            const isActive = activeKey === sector.key;
            const fill = QUADRANT_COLOR[sector.quadrant] ?? "var(--accent)";
            const trail = sector.trail ?? [];
            const trailPts =
              trail.length > 1
                ? trail.map((t) => `${toX(t.rs_ratio)},${toY(t.rs_momentum)}`).join(" ")
                : null;

            return (
              <g
                key={sector.key}
                className="cursor-pointer"
                onMouseEnter={() => setHoveredKey(sector.key)}
                onMouseLeave={() => setHoveredKey(null)}
                onClick={() => onSelectSector(isSelected ? null : sector.key)}
              >
                {isActive && trailPts ? (
                  <>
                    <polyline
                      points={trailPts}
                      fill="none"
                      stroke={fill}
                      strokeWidth={2}
                      strokeOpacity={0.75}
                    />
                    {trail.slice(0, -1).map((pt, i) => (
                      <circle
                        key={`${sector.key}-t-${i}`}
                        cx={toX(pt.rs_ratio)}
                        cy={toY(pt.rs_momentum)}
                        r={2.5}
                        fill={fill}
                        opacity={0.5}
                      />
                    ))}
                  </>
                ) : null}

                <circle
                  cx={x}
                  cy={y}
                  r={isSelected ? 7.5 : isActive ? 6.5 : 5}
                  fill={fill}
                  stroke="var(--surface-raised)"
                  strokeWidth={isSelected ? 2.5 : 1.5}
                />
                <text
                  x={x + 8}
                  y={y + 4}
                  fontSize={isSelected || isActive ? "11.5" : "10.5"}
                  fontWeight={isSelected || isActive ? "700" : "500"}
                  fill="var(--text-primary)"
                >
                  {sector.nse_name.replace("Nifty ", "")}
                </text>
              </g>
            );
          })}

          {/* Axis labels */}
          <text x={W / 2} y={H - 8} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
            RS-Ratio (Relative Strength vs Benchmark)
          </text>
        </svg>
      </div>

      {unplaced.length > 0 ? (
        <p className="mt-2 text-[11px] text-text-muted">
          Unplaced ({unplaced.length}):{" "}
          {unplaced.map((u) => u.nse_name.replace("Nifty ", "")).join(", ")} (insufficient history)
        </p>
      ) : null}
    </div>
  );
}
