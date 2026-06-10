import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { API_BASE, getJSON } from "../api";
import { Panel, Help, Btn } from "../components/ui";

export default function Logs() {
  const [level, setLevel] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [auto, setAuto] = useState(true);

  const load = async () => {
    try {
      const d = await getJSON(`/api/system/logs?limit=400${level ? `&level=${level}` : ""}`);
      setLines(d.lines ?? []);
    } catch { /* server away */ }
  };

  useEffect(() => { load(); }, [level]);
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, level]);

  const colorFor = (line: string) =>
    line.includes("ERROR") ? "text-rose-400" :
    line.includes("WARNING") ? "text-amber-400" :
    line.includes("INFO") ? "text-slate-300" : "text-slate-500";

  return (
    <div className="space-y-6">
      <Help text="Live tail of the bot's runtime log — every scan, entry, exit, guard block and LLM call leaves a line here. Auto-refreshes every 4 seconds while open." />
      <Panel title="System Log"
        actions={
          <div className="flex items-center gap-2">
            <select value={level} onChange={(e) => setLevel(e.target.value)}
              className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2 py-1.5 text-xs text-slate-300 outline-none">
              <option value="">All levels</option>
              <option value="INFO">INFO+</option>
              <option value="WARNING">WARNING+</option>
              <option value="ERROR">ERROR</option>
            </select>
            <label className="flex items-center gap-1.5 text-[10px] text-slate-400">
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> auto
            </label>
            <a href={`${API_BASE}/api/system/logs/download`}>
              <Btn><Download size={11} /> Download</Btn>
            </a>
          </div>
        }>
        <div className="bg-[#05091a] border border-slate-800/70 rounded-xl p-3 max-h-[560px] overflow-auto font-mono text-[10px] leading-relaxed">
          {lines.length === 0
            ? <span className="text-slate-600">No log lines (is the bot process running?)</span>
            : lines.map((l, i) => <div key={i} className={colorFor(l)}>{l}</div>)}
        </div>
      </Panel>
    </div>
  );
}
