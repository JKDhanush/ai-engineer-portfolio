// Everything the UI needs from the FastAPI backend: types, the auth token, and a Server-Sent Events reader.

export type Source = {
  id: string; cited: boolean; doc_id: string; title: string; circular_no: string | null; issued_on: string | null;
  status: string; status_reason: string | null; entity_type: string | null; section_path: string; pages: string;
  pdf_url: string | null; score: number; also_in: string[]; text: string;
};

export type CitationCheck = {
  ok: boolean; refused: boolean; invalid_refs: number[]; uncited_sentences: string[];
  unsupported_sentences: string[]; unsupported_numbers: string[];
};

export type Done = {
  citation_check: CitationCheck; cited: number[]; notes: string[]; provider: string | null; model: string | null;
  cache: "miss" | "exact" | "semantic"; cost_usd: number;
  usage: { prompt_tokens: number; completion_tokens: number };
  timings_ms: { retrieval: number; first_token: number | null; total: number };
};

export type Meta = { standalone_question: string; entity: string | null; mode: string; prefer_active: boolean };

export type Turn = { role: "user" | "assistant"; content: string };

export type User = { id: string | null; email: string; role: string; access_levels: string[]; auth_required?: boolean };

const TOKEN_KEY = "ciq_token";

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }   // storage can be unavailable
}

export function setToken(token: string | null) {
  try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export class AuthError extends Error {}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init, headers: { "Content-Type": "application/json", ...authHeaders(), ...(init.headers ?? {}) },
  });
  if (res.status === 401) throw new AuthError("Please sign in");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? res.statusText);
  }
  return res.json();
}

export type AskHandlers = {
  onMeta?: (m: Meta) => void; onSources?: (s: Source[]) => void; onToken?: (t: string) => void;
  onDone?: (d: Done) => void;
};

/** POST /ask/stream and dispatch each SSE event. fetch() (not EventSource) because we need POST + headers. */
export async function askStream(body: object, h: AskHandlers, signal?: AbortSignal): Promise<void> {
  const res = await fetch("/api/ask/stream", {
    method: "POST", signal, headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (res.status === 401) throw new AuthError("Please sign in");
  if (res.status === 429) throw new Error("Too many questions in a minute. Wait a moment and try again.");
  if (!res.ok || !res.body) {
    const b = await res.json().catch(() => ({}));
    throw new Error(b.detail ?? res.statusText);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {               // events are separated by a blank line
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const event = raw.match(/^event: (.*)$/m)?.[1];
      const data = JSON.parse(raw.match(/^data: (.*)$/m)?.[1] ?? "null");
      if (event === "meta") h.onMeta?.(data);
      else if (event === "sources") h.onSources?.(data);
      else if (event === "token") h.onToken?.(data);
      else if (event === "done") h.onDone?.(data);
      else if (event === "error") throw new Error(data);
    }
  }
}

export const ENTITIES: [string, string][] = [
  ["", "All entities"], ["commercial_banks", "Commercial banks"], ["nbfcs", "NBFCs"],
  ["small_finance_banks", "Small finance banks"], ["urban_coop_banks", "Urban co-operative banks"],
];
