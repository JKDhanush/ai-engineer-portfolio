"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, AuthError } from "@/lib/api";

type Stats = {
  queries: number; cache_hit_rate: number | null; refusal_rate: number | null; citation_ok_rate: number | null;
  p50_ms: number | null; p95_ms: number | null; p50_first_token_ms: number | null; total_cost_usd: number | null;
  avg_cost_usd: number | null; tokens: number | null; window_hours: number;
  by_provider: { provider: string; n: number; cost_usd: number }[];
};

const pct = (v: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const ms = (v: number | null) => (v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);

export default function AdminPage() {
  const router = useRouter();
  const [hours, setHours] = useState(24);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Stats>(`/admin/stats?hours=${hours}`).then(setStats).catch((e) => {
      if (e instanceof AuthError) router.push("/login"); else setError(e.message);
    });
  }, [hours, router]);

  const tiles: [string, string, string][] = stats ? [
    ["Questions", String(stats.queries), `last ${stats.window_hours} h`],
    ["Cache hit rate", pct(stats.cache_hit_rate), "answered without the LLM"],
    ["Citation check passed", pct(stats.citation_ok_rate), "of answered questions"],
    ["Refused", pct(stats.refusal_rate), "nothing relevant in the corpus"],
    ["Latency p50 / p95", `${ms(stats.p50_ms)} / ${ms(stats.p95_ms)}`, "full answer"],
    ["First word p50", ms(stats.p50_first_token_ms), "what the user feels"],
    ["Cost", `$${(stats.total_cost_usd ?? 0).toFixed(4)}`, `avg $${(stats.avg_cost_usd ?? 0).toFixed(5)} / question`],
    ["Tokens", (stats.tokens ?? 0).toLocaleString("en-IN"), "prompt + completion"],
  ] : [];

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <div className="flex items-baseline gap-4">
        <h1 className="text-xl font-semibold text-ink">Usage & cost</h1>
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))}
          className="rounded-md border border-slate-200 bg-white px-2 py-1 text-sm">
          <option value={1}>Last hour</option><option value={24}>Last 24 hours</option>
          <option value={168}>Last 7 days</option><option value={720}>Last 30 days</option>
        </select>
      </div>
      {error && <p className="mt-4 text-sm text-red-700">{error}</p>}
      <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(([label, value, sub]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">{label}</div>
            <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
            <div className="mt-1 text-xs text-slate-400">{sub}</div>
          </div>))}
      </div>
      {stats && stats.by_provider.length > 0 && (
        <table className="mt-8 w-full rounded-xl border border-slate-200 bg-white text-sm">
          <thead><tr className="text-left text-slate-500">
            <th className="p-3 font-medium">Answered by</th><th className="p-3 font-medium">Questions</th>
            <th className="p-3 font-medium">Cost</th></tr></thead>
          <tbody>{stats.by_provider.map((p) => (
            <tr key={p.provider} className="border-t border-slate-100">
              <td className="p-3">{p.provider}</td><td className="p-3">{p.n}</td>
              <td className="p-3">${p.cost_usd.toFixed(4)}</td></tr>))}</tbody>
        </table>)}
    </main>
  );
}
