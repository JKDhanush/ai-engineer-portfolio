"use client";

import type { Source } from "@/lib/api";

export function SourceCard({ s, highlighted }: { s: Source; highlighted: boolean }) {
  const active = s.status === "active";
  return (
    <div id={`src-${s.id}`} className={`rounded-lg border bg-white p-3 text-sm transition ${highlighted
      ? "border-accent ring-2 ring-accent/30" : s.cited ? "border-accent/40" : "border-slate-200"}`}>
      <div className="flex items-start gap-2">
        <span className="font-semibold text-accent">{s.id}</span>
        <span className="font-medium text-slate-800 flex-1">{s.title}</span>
        <span className={`shrink-0 rounded-full border px-2 text-[11px] ${active
          ? "border-emerald-300 text-emerald-700" : "border-amber-300 text-amber-700"}`}>{s.status}</span>
      </div>
      <div className="mt-1 text-xs text-slate-500">
        {[s.circular_no, s.issued_on, s.section_path, `p. ${s.pages}`].filter(Boolean).join(" · ")}
        {s.pdf_url && <> · <a className="text-accent underline" href={s.pdf_url} target="_blank" rel="noopener noreferrer">PDF</a></>}
      </div>
      {!active && s.status_reason && <div className="mt-1 text-xs text-amber-700">⚠ {s.status_reason}</div>}
      {s.also_in.length > 0 && <div className="mt-1 text-xs text-slate-500">Same rule also in: {s.also_in.join("; ")}</div>}
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-slate-600">Show paragraph</summary>
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 font-sans text-xs text-slate-700">{s.text}</pre>
      </details>
    </div>
  );
}
