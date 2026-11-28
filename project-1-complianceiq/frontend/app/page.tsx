"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnswerMeta, AnswerText, CheckBadge } from "@/components/Answer";
import { SourceCard } from "@/components/SourceCard";
import { AuthError, askStream, ENTITIES, type Done, type Meta, type Source, type Turn } from "@/lib/api";

type Exchange = { question: string; answer: string; sources: Source[]; meta: Meta | null; done: Done | null;
                  error: string | null };

const EXAMPLES = [
  "How often must KYC be updated for high-risk customers?",
  "What are the requirements for Video-based Customer Identification (V-CIP)?",
  "Who is a beneficial owner when the customer is a company?",
  "What is the limit on balances in a small account?",
];

export default function AskPage() {
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [entity, setEntity] = useState("");
  const [includeSuperseded, setIncludeSuperseded] = useState(true);
  const [chat, setChat] = useState<Exchange[]>([]);
  const [selected, setSelected] = useState<number | null>(null);     // which exchange the sources panel shows
  const [highlight, setHighlight] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [chat.length]);

  const update = (i: number, patch: Partial<Exchange> | ((e: Exchange) => Partial<Exchange>)) =>
    setChat((c) => c.map((e, j) => (j === i ? { ...e, ...(typeof patch === "function" ? patch(e) : patch) } : e)));

  async function ask(q: string) {
    q = q.trim();
    if (q.length < 3 || busy) return;
    const history: Turn[] = chat.filter((e) => e.done).slice(-2)
      .flatMap((e) => [{ role: "user", content: e.question }, { role: "assistant", content: e.answer }]);
    const i = chat.length;
    setChat((c) => [...c, { question: q, answer: "", sources: [], meta: null, done: null, error: null }]);
    setSelected(i); setHighlight(null); setQuestion(""); setBusy(true);
    abort.current = new AbortController();
    try {
      await askStream({ question: q, entity: entity || null, include_superseded: includeSuperseded, history }, {
        onMeta: (meta) => update(i, { meta }),
        onSources: (sources) => update(i, { sources }),
        onToken: (t) => update(i, (e) => ({ answer: e.answer + t })),
        onDone: (done) => update(i, (e) => ({ done, sources: e.sources.map((s, k) => ({ ...s,
          cited: done.cited.includes(k + 1) })) })),
      }, abort.current.signal);
    } catch (err) {
      if (err instanceof AuthError) { router.push("/login"); return; }
      if ((err as Error).name !== "AbortError") update(i, { error: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const cite = (i: number, n: number) => {
    setSelected(i); setHighlight(`S${n}`);
    setTimeout(() => document.getElementById(`src-S${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
  };

  const panel = selected !== null ? chat[selected] : null;

  return (
    <main className="mx-auto grid max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_420px]">
      <section className="flex min-h-[calc(100vh-7rem)] flex-col">
        {chat.length === 0 ? (
          <div className="py-10">
            <h1 className="text-2xl font-semibold text-ink">Ask about RBI KYC / AML rules</h1>
            <p className="mt-2 max-w-xl text-slate-600">Answers come only from the RBI Directions and cite the exact
              circular and paragraph. Repealed rules are flagged; if the documents don&apos;t cover it, you&apos;ll be told.</p>
            <div className="mt-6 grid gap-2 sm:grid-cols-2">
              {EXAMPLES.map((e) => (
                <button key={e} onClick={() => ask(e)}
                  className="rounded-lg border border-slate-200 bg-white p-3 text-left text-sm text-slate-700 hover:border-accent/50">
                  {e}</button>))}
            </div>
          </div>
        ) : (
          <div className="flex-1 space-y-6">
            {chat.map((e, i) => (
              <article key={i} onClick={() => setSelected(i)}
                className={`rounded-xl border bg-white p-4 shadow-sm ${selected === i ? "border-accent/40" : "border-slate-200"}`}>
                <div className="mb-3 font-medium text-ink">{e.question}</div>
                {e.error ? <p className="text-sm text-red-700">{e.error}</p>
                  : !e.answer ? <p className="text-sm text-slate-500">Searching the RBI documents…</p>
                  : <AnswerText text={e.answer} streaming={!e.done} onCite={(n) => cite(i, n)} />}
                {e.done && (
                  <div className="mt-3 space-y-2"><CheckBadge c={e.done.citation_check} />
                    <AnswerMeta done={e.done} meta={e.meta} question={e.question} /></div>)}
              </article>))}
            <div ref={bottom} />
          </div>
        )}

        <form className="sticky bottom-0 mt-6 rounded-xl border border-slate-200 bg-white p-3 shadow-sm"
          onSubmit={(ev) => { ev.preventDefault(); ask(question); }}>
          <textarea value={question} onChange={(ev) => setQuestion(ev.target.value)} rows={2}
            onKeyDown={(ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); ask(question); } }}
            placeholder={chat.length ? "Ask a follow-up, e.g. “what about NBFCs?”" : "Ask a question…"}
            className="w-full resize-none bg-transparent text-sm outline-none" />
          <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <select value={entity} onChange={(ev) => setEntity(ev.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2 py-1">
              {ENTITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={includeSuperseded} onChange={(ev) => setIncludeSuperseded(ev.target.checked)} />
              include superseded
            </label>
            {chat.length > 0 && <button type="button" className="underline" disabled={busy}
              onClick={() => { setChat([]); setSelected(null); }}>New chat</button>}
            {busy
              ? <button type="button" onClick={() => abort.current?.abort()}
                  className="ml-auto rounded-md border border-slate-300 px-4 py-1.5">Stop</button>
              : <button type="submit" className="ml-auto rounded-md bg-accent px-4 py-1.5 text-white disabled:opacity-50"
                  disabled={question.trim().length < 3}>Ask</button>}
          </div>
        </form>
      </section>

      <aside className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-auto">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Sources</h2>
        {!panel || panel.sources.length === 0
          ? <p className="text-sm text-slate-500">The paragraphs behind each answer appear here. Click a citation
              like <span className="rounded bg-accent/10 px-1 text-xs font-semibold text-accent">S1</span> to jump to it.</p>
          : <div className="space-y-3">{panel.sources.map((s) =>
              <SourceCard key={s.id} s={s} highlighted={highlight === s.id && panel === chat[selected!]} />)}</div>}
      </aside>
    </main>
  );
}
