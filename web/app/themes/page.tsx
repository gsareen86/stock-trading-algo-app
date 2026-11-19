import { Unavailable } from "@/components/states";
import { ThemesExplorer } from "@/components/themes-explorer";
import { fetchThemes } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ThemesPage() {
  const result = await fetchThemes();

  if (!result.ok) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-10">
        <Unavailable result={result} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <ThemesExplorer
        themes={result.data.themes}
        latestRun={result.data.latest_run}
      />
    </div>
  );
}
