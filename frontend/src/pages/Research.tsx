import { useState } from "react";
import { ChevronDown, ChevronUp, Zap } from "lucide-react";
import { fmtIST, fmtNum, postJSON } from "../api";
import { Panel, useApi, Badge, DataTable, EmptyState, Help, toast, Btn, RefreshBtn, SearchBox } from "../components/ui";
import { takeTicker } from "../nav";

function VerdictRow({ r }: { r: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="bg-slate-900/50 border border-slate-800/70 rounded-xl p-3">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 text-left">
        <span className="font-bold text-slate-100 text-sm w-28">{r.ticker}</span>
        <Badge text={r.verdict || "—"} />
        <Badge text={r.outlook || "—"} />
        <span className="text-xs font-mono text-slate-400">mgmt {fmtNum(r.management_score, 0)}</span>
        {r.guidance_credibility != null && (
          <span className="text-xs font-mono text-indigo-300" title="Guidance credibility — % of past guidance delivered (recency-weighted)">
            credibility {fmtNum(r.guidance_credibility, 0)}
          </span>
        )}
        <span className="flex-1 text-[10px] text-slate-500 truncate">{r.thesis}</span>
        <span className="text-[10px] text-slate-600">{fmtIST(r.researched_at)}</span>
        {open ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>
      {open && (
        <div className="mt-3 space-y-3 text-[11px] leading-relaxed">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="text-slate-500 font-semibold uppercase text-[9px] mb-1">Thesis</div>
              <p className="text-slate-300 m-0">{r.thesis || "—"}</p>
              <div className="text-slate-500 font-semibold uppercase text-[9px] mt-3 mb-1">Recommendation</div>
              <p className="text-slate-300 m-0">{r.recommendation} — {r.recommendation_rationale}</p>
              <div className="text-slate-500 font-semibold uppercase text-[9px] mt-3 mb-1">Management Guidance (restated)</div>
              <p className="text-slate-300 m-0">{r.guidance || "none given"}</p>
            </div>
            <div>
              <div className="text-emerald-500 font-semibold uppercase text-[9px] mb-1">Positives</div>
              <ul className="m-0 pl-4 text-slate-300">{(r.key_positives ?? []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
              <div className="text-rose-500 font-semibold uppercase text-[9px] mt-3 mb-1">Risks</div>
              <ul className="m-0 pl-4 text-slate-300">{(r.key_risks ?? []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
            </div>
          </div>
          {/* Full LLM commentary — the two stage summaries behind the verdict.
              Informational only; shown verbatim so nothing is lost between
              the model and the user. */}
          {r.concall_summary && (
            <details className="bg-slate-950/60 border border-slate-800/70 rounded-lg p-3">
              <summary className="cursor-pointer text-indigo-300 font-semibold text-[10px] uppercase tracking-wider">
                Concall Summary — full LLM commentary ({r.concall_date || "latest call"})
              </summary>
              <pre className="mt-2 whitespace-pre-wrap font-sans text-slate-300 text-[11px] leading-relaxed m-0 max-h-96 overflow-auto">{r.concall_summary}</pre>
            </details>
          )}
          {r.fundamentals_summary && (
            <details className="bg-slate-950/60 border border-slate-800/70 rounded-lg p-3">
              <summary className="cursor-pointer text-indigo-300 font-semibold text-[10px] uppercase tracking-wider">
                Fundamentals Read — full LLM commentary
              </summary>
              <pre className="mt-2 whitespace-pre-wrap font-sans text-slate-300 text-[11px] leading-relaxed m-0 max-h-96 overflow-auto">{r.fundamentals_summary}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

export default function Research() {
  const research = useApi<any[]>("/api/positional/research");
  const navTicker = useState(() => takeTicker())[0];
  const [gTicker, setGTicker] = useState(navTicker);
  const guidance = useApi<any>(`/api/engine/guidance${gTicker ? `?ticker=${encodeURIComponent(gTicker)}` : ""}`, [gTicker]);
  const [q, setQ] = useState(navTicker);
  const [reTicker, setReTicker] = useState("");
  const [busy, setBusy] = useState(false);

  const rows = (research.data ?? []).filter((r) =>
    !q || r.ticker.toLowerCase().includes(q.toLowerCase()) || (r.verdict ?? "").toLowerCase().includes(q.toLowerCase()));

  const reResearch = async () => {
    if (!reTicker.trim()) { toast("Enter a ticker first."); return; }
    setBusy(true);
    try {
      const r = await postJSON(`/api/positional/research/ticker/${reTicker.trim().toUpperCase()}`, {});
      toast(r.message ?? "Research started — refresh in a minute or two.");
    } catch (e: any) { toast(`Research failed: ${e.message}`); }
    setBusy(false);
  };

  return (
    <div className="space-y-6">
      <Help text="The LLM analyst reads each shortlisted company's latest concall + fundamentals and produces a verdict (PROCEED / REDUCE / SKIP), a management score and a thesis. The guidance ledger below makes management accountable: every forward commitment is stored, reconciled against actual results the next quarter, and rolled into a credibility score that feeds the durability axis." />

      <Panel title="Research Verdicts" subtitle="Latest LLM read per company — click a row for the full thesis, positives, risks and restated guidance"
        actions={
          <div className="flex items-center gap-2">
            <SearchBox value={q} onChange={setQ} placeholder="Filter ticker/verdict…" />
            <RefreshBtn onClick={research.reload} loading={research.loading} />
          </div>
        }>
        <div className="space-y-2 max-h-[480px] overflow-auto pr-1">
          {rows.length === 0
            ? <EmptyState>No research yet. It runs automatically on scan candidates and holdings (08:30 IST refresh), or trigger one below.</EmptyState>
            : rows.map((r) => <VerdictRow key={r.ticker} r={r} />)}
        </div>
        <div className="mt-4 flex items-center gap-2 border-t border-slate-800/70 pt-3">
          <input value={reTicker} onChange={(e) => setReTicker(e.target.value)} placeholder="TICKER"
            className="bg-slate-900/70 border border-slate-700/60 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono outline-none w-32 uppercase" />
          <Btn kind="primary" busy={busy} onClick={reResearch}><Zap size={11} /> Research this ticker now</Btn>
          <span className="text-[10px] text-slate-500">Runs the full concall pipeline for one name (takes 1–3 min).</span>
        </div>
      </Panel>

      <Panel title="Guidance Ledger" subtitle="Management's promises, verbatim, with the verdict once actuals arrive. MET/BEAT raise credibility; MISSED lowers it — two misses in a row trigger a review alert (and a thesis stop in the LT book)."
        actions={
          <div className="flex items-center gap-2">
            <SearchBox value={gTicker} onChange={setGTicker} placeholder="Filter by ticker…" />
            <RefreshBtn onClick={guidance.reload} loading={guidance.loading} />
          </div>
        }>
        <DataTable
          rows={guidance.data?.rows ?? []}
          empty={<EmptyState>Ledger is empty. Rows appear automatically after research runs on a company whose concall contained forward guidance; reconciliation happens ~70 days later when the next results land.</EmptyState>}
          cols={[
            { key: "ticker", label: "Ticker", render: (r) => <span className="font-bold text-slate-100">{r.ticker}</span> },
            { key: "source_quarter", label: "From Qtr" },
            { key: "metric", label: "Metric" },
            { key: "guided_value", label: "Guided", render: (r) => <span className="whitespace-normal text-[10px]">{r.guided_value}</span> },
            { key: "guided_low", label: "Band", align: "right", render: (r) => r.guided_low != null || r.guided_high != null ? `${r.guided_low ?? "?"}–${r.guided_high ?? "?"}` : "—" },
            { key: "horizon", label: "Horizon" },
            { key: "actual_value", label: "Actual", align: "right", render: (r) => fmtNum(r.actual_value, 1) },
            { key: "delivered", label: "Delivered", render: (r) => r.delivered ? <Badge text={r.delivered} /> : <Badge text="AWAITING" tone="PENDING" /> },
          ]}
        />
        {guidance.data?.credibility && Object.keys(guidance.data.credibility).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(guidance.data.credibility).map(([t, c]: any) => (
              <span key={t} className="text-[10px] font-mono px-2 py-1 rounded-lg bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                {t}: credibility {fmtNum(c, 0)}/100
              </span>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
