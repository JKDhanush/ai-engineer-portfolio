"use client";

import type { CitationCheck, Done, Meta } from "@/lib/api";

/** Minimal markdown: paragraphs, bullet lists, **bold**, and clickable [S1] citations. No HTML injection:
 *  text is rendered as React children, never via dangerouslySetInnerHTML. */
export function AnswerText({ text, onCite, streaming }: { text: string; onCite: (n: number) => void;
                                                         streaming?: boolean }) {
  const blocks: { list: boolean; lines: string[] }[] = [];
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*[-*•]\s+(.*)/);
    if (!line.trim()) continue;
    const isList = !!m;
    const last = blocks[blocks.length - 1];
    if (isList && last?.list) last.lines.push(m![1]);
    else blocks.push({ list: isList, lines: [isList ? m![1] : line] });
  }
  const inline = (s: string, key: string) =>
    s.split(/(\[S\d+\]|\*\*[^*]+\*\*)/g).map((part, i) => {
      const cite = part.match(/^\[S(\d+)\]$/);
      if (cite) return (
        <button key={`${key}-${i}`} onClick={() => onCite(Number(cite[1]))}
          className="mx-0.5 rounded bg-accent/10 px-1 text-xs font-semibold text-accent hover:bg-accent/20">
          S{cite[1]}</button>);
      if (part.startsWith("**")) return <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>;
      return <span key={`${key}-${i}`}>{part}</span>;
    });
  return (
    <div className={`space-y-2 leading-relaxed ${streaming ? "cursor" : ""}`}>
      {blocks.map((b, i) => b.list
        ? <ul key={i} className="list-disc pl-5 space-y-1">{b.lines.map((l, j) => <li key={j}>{inline(l, `${i}-${j}`)}</li>)}</ul>
        : <p key={i}>{inline(b.lines[0], `${i}`)}</p>)}
    </div>
  );
}

export function CheckBadge({ c }: { c: CitationCheck }) {
  if (c.refused) return <Badge tone="neutral">No supporting source found, so no answer was made up</Badge>;
  if (c.ok) return <Badge tone="ok">✓ Every cited sentence matches its source</Badge>;
  const issues: string[] = [];
  if (c.invalid_refs.length) issues.push(`cites missing source ${c.invalid_refs.map((n) => `S${n}`).join(", ")}`);
  if (c.unsupported_numbers.length) issues.push(`numbers not in sources: ${c.unsupported_numbers.join(", ")}`);
  if (c.unsupported_sentences.length) issues.push(`${c.unsupported_sentences.length} weakly supported sentence(s)`);
  if (c.uncited_sentences.length) issues.push(`${c.uncited_sentences.length} sentence(s) without citation`);
  return <Badge tone="warn">⚠ Check before relying on this: {issues.join("; ")}</Badge>;
}

function Badge({ tone, children }: { tone: "ok" | "warn" | "neutral"; children: React.ReactNode }) {
  const cls = { ok: "bg-emerald-50 text-emerald-800 border-emerald-200",
                warn: "bg-amber-50 text-amber-800 border-amber-200",
                neutral: "bg-slate-50 text-slate-700 border-slate-200" }[tone];
  return <div className={`inline-block rounded-md border px-2.5 py-1 text-xs ${cls}`}>{children}</div>;
}

export function AnswerMeta({ done, meta, question }: { done: Done; meta: Meta | null; question: string }) {
  const t = done.timings_ms;
  const bits = [
    done.cache !== "miss" ? `⚡ cache: ${done.cache}` : `${done.provider ?? ""} ${done.model ?? ""}`.trim(),
    `retrieval ${t.retrieval} ms`, `first word ${t.first_token ?? "–"} ms`, `total ${t.total} ms`,
    done.cost_usd ? `$${done.cost_usd.toFixed(5)}` : "₹0",
  ].filter(Boolean);
  return (
    <div className="space-y-1 text-xs text-slate-500">
      {done.notes.map((n) => <div key={n} className="text-amber-700">ⓘ {n}</div>)}
      {meta && meta.standalone_question !== question && <div>searched for: “{meta.standalone_question}”</div>}
      {meta?.entity && <div>entity filter: {meta.entity.replaceAll("_", " ")}</div>}
      <div>{bits.join(" · ")}</div>
    </div>
  );
}
