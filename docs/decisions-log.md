# Architecture Decision Records (ADRs)

An ADR records one significant decision: the context, what we chose, and what it costs us.
Decisions are never deleted; if one changes, a new ADR supersedes it.

**Template**
```
## ADR-NNN: Title
- Date / Status (Proposed | Accepted | Superseded by ADR-XXX)
- Context: what problem forced a decision?
- Decision: what we chose.
- Alternatives: what else we considered and why not.
- Consequences: what gets easier, what gets harder.
```

---

## ADR-001: pgvector in Postgres instead of a dedicated vector database
- **Date:** 2026-11 · **Status:** Accepted
- **Context:** P1 needs vector search, keyword search, metadata filters (circular status, date, ACL) and relational data (documents, versions, users), on a corpus of thousands to low millions of chunks.
- **Decision:** Store vectors in Postgres with pgvector (HNSW index) next to everything else.
- **Alternatives:** Pinecone / Qdrant / Weaviate. They're strong at very large scale, but they mean a second datastore to sync, secure, back up and pay for, and filters plus joins become harder.
- **Consequences:** + one database, one backup, transactional consistency, hybrid search in a single SQL query, and RDS-ready. − At hundreds of millions of vectors a dedicated engine would win; we'll revisit if that ever applies.

## ADR-002: Async FastAPI with asyncpg
- **Date:** 2026-11 · **Status:** Accepted
- **Context:** A RAG request is mostly *waiting*: on the DB, the reranker and LLM APIs (seconds of streaming).
- **Decision:** async FastAPI + asyncpg + redis.asyncio, with shared pools created in the app lifespan.
- **Alternatives:** Sync Flask/Django: one worker is blocked per in-flight LLM call, so you need far more processes for the same concurrency.
- **Consequences:** + high concurrency per process, native SSE streaming. − any blocking call (CPU-heavy parsing, sync SDKs) must be moved off the event loop (thread pool or worker).

## ADR-003: No LangChain / LlamaIndex in P1
- **Date:** 2026-11 · **Status:** Accepted
- **Context:** P1's purpose is to master RAG internals: chunking, fusion, reranking and evals.
- **Decision:** Build the pipeline by hand with small, explicit modules.
- **Alternatives:** Frameworks give quicker demos but hide the retrieval details the evals need to measure and tune.
- **Consequences:** + full control, every step measurable in the ablation table, strong interview depth. − more code to write. P2 uses LangGraph deliberately, once the fundamentals are known.

## ADR-004: Linux dev environment with Docker Engine and uv
- **Date:** 2026-11-21 · **Status:** Accepted
- **Context:** Moved development from Windows to Ubuntu 26.04 LTS. Ubuntu 26.04 ships Python 3.14 only; the project targets 3.12.
- **Decision:** Docker Engine + Compose plugin (not Docker Desktop). uv manages the Python version (3.12) and installs packages, locally and inside the Docker image.
- **Alternatives:** Docker Desktop adds a VM that native Linux doesn't need. deadsnakes PPA + pip is slower and needs a separate Python install method.
- **Consequences:** + the laptop matches the EC2/ECS runtime, the local venv matches the container's Python, and installs are roughly 10× faster. − uv is newer than pip, so the team needs to know it (widely adopted by 2026).

## ADR-005: Free, local-first model stack (GPU embeddings + reranker, local/free-tier LLM)
- **Date:** 2026-11-21 · **Status:** Accepted
- **Context:** Budget is ₹0 until deployment. The dev laptop has an RTX 3050 Laptop GPU with 6 GB VRAM (CUDA 13.2). The schema already fixes embeddings at 1024 dims.
- **Decision:** Embeddings use **BAAI/bge-m3** (1024-d) and reranking uses **BAAI/bge-reranker-v2-m3**, both run locally on the GPU. Generation uses **Ollama** (a 4-bit 7–8B model) with a **free-tier API** as fallback, behind our own provider interface. Bedrock is added as a provider at M7/M9.
- **Alternatives:** Bedrock Titan / Cohere embeddings would cost per token and need network on every re-index. OpenAI embeddings would mean a paid account plus 1536/3072 dims (a schema change).
- **Consequences:** + ₹0 cost, unlimited re-indexing while tuning chunking, strong open models, and the provider abstraction is exercised from day one. − 6 GB VRAM means models run one at a time (no LLM and reranker together at full size), and local LLM quality is below frontier APIs, which the M6 evals will quantify. The embedding model is now part of the data contract: changing it means re-embedding everything.

## ADR-006: Structure-aware parsing and parent-child chunking for RBI documents
- **Date:** 2026-11-22 · **Status:** Accepted
- **Context:** `inspect_pdf.py` on the 22-PDF corpus (~660 pages, ~1.3M chars) showed:
  - all PDFs have a text layer (1.3k–2.3k chars/page), so no OCR is needed;
  - headings are the **same font size as body text** (12 pt) but **bold** and patterned (`Chapter VI – …`, `A. …`, `F.1 …`);
  - paragraphs use a 4-level numbering scheme (`27.` → `(1)` → `(ii)` → `(a)`), which is what regulatory citations point to;
  - 9 pt **footnotes record amendment history** ("Inserted with effect from <date> vide <Amendment Directions>");
  - noise: 2-page table of contents (dot leaders), a page number as the first line of every page, a mis-encoded Hindi header;
  - a few tables (max 15 per document) with merged cells and lost spaces;
  - heavy **near-duplication**: the CB/NBFC/SFB/UCB KYC Directions share most of their text, and the annexes (MHA orders) are repeated per entity.
- **Decision:**
  1. **Parser:** PyMuPDF at the line/span level (text + font size + bold flag + page), *not* plain text or generic Markdown conversion, because we need bold, font size and position to recover structure. Drop TOC pages, page numbers and the Hindi masthead.
  2. **Structure tree:** Document → Chapter → Section (`A.`, `F.1`) → Paragraph (`27.`) → Clause (`(1)`, `(ii)`, `(a)`). Every chunk carries a `section_path`, e.g. `Chapter VI > E. On-going Due Diligence > Para 38(1)`.
  3. **Chunking by structure, not by character count:** a **parent** = one top-level paragraph (split at clause boundaries only if it exceeds ~1,200 tokens); **children** = its clauses packed to ~150–350 tokens, never crossing a paragraph boundary. Children are embedded and searched; parents are sent to the LLM.
  4. **Contextual header** prepended to every chunk before embedding and stored in `context_header` (tsvector weight A): `<document title> | <circular no.> | <date> | <section_path>`.
  5. **Footnotes** are removed from the body text and parsed into per-paragraph amendment events (`inserted/substituted/deleted`, effective date, source circular), which feeds the version graph in M5.
  6. **Tables** become their own chunks, serialized row by row as `header: value` lines, so each row stays readable and searchable.
  7. **Metadata** (circular numbers, date, title) is extracted from the page-1 header block by regex, and **checked against `data/manifest.csv` as ground truth**, with accuracy reported.
  8. **Duplicates are kept, not deleted:** every chunk stores a normalized `content_hash` plus the document's `entity_type`. Retrieval filters by entity and collapses identical hashes, because an NBFC's rule and a bank's rule can be textually identical yet still need separate citations.
- **Alternatives:** fixed-size character/token windows (simple, but cut rules mid-clause and lose citation anchors); generic PDF→Markdown (loses the bold/footnote signals we rely on); deleting cross-document duplicates at ingest (breaks per-entity citations and ACLs).
- **Consequences:** + chunks align with how compliance officers cite rules; precise `section_path` citations; amendment history captured for free. − the parser is RBI-specific (heading/numbering regexes); SEBI documents will need their own rules, so the parser is designed as a pluggable class per regulator. Chunk-size targets are a starting point and will be tuned against the M2 eval set.

## ADR-007: In development the API runs on the host; Docker runs only the data services
- **Date:** 2026-11-22 · **Status:** Accepted
- **Context:** `/search` and `/ask` must embed the question with bge-m3 on the GPU (ADR-005), and the LLM runs in Ollama on the host. The API image is deliberately slim (no torch, ~2 GB smaller), and GPU access from a container needs the NVIDIA Container Toolkit.
- **Decision:** `make up` starts Postgres + Redis in Docker; `make api` runs FastAPI from the local venv (`uvicorn --reload`) with GPU access. The containerised API stays available behind a Compose profile (`make docker-api`) for health checks.
- **Alternatives:** put torch + CUDA in the API image and use the NVIDIA Container Toolkit (heavier image, more setup, revisit at M9); call a hosted embedding API (costs money, breaks the ₹0 budget).
- **Consequences:** + fast edit-reload loop, GPU available, simple setup. − dev and prod run the API differently; at M9 we decide between a GPU container, a separate embedding service, or a hosted embedding API, and the `/health` check already reports `embedder` and `llm` separately to support that.

## ADR-008: Evaluation-first: a paragraph-level golden set with cross-document equivalence
- **Date:** 2026-11-23 · **Status:** Accepted
- **Context:** Without measurement, every retrieval change (reranking, query rewriting, chunk sizes) is a guess. The corpus repeats the same rule in four entity directions and the repealed 2016 Master Direction, under different paragraph numbers (periodic updation is Para 42 / 42 / 43 / 41 / 38).
- **Decision:** 175 hand-written questions (165 answerable, 10 out-of-scope) in `evals/golden_questions.py`, each pointing at the paragraph that answers it in the Commercial Banks directions. `build_golden.py` finds the equivalent paragraph in every other document by TF-IDF similarity (same annex only for annex paragraphs), so retrieving the rule from any copy counts. Metrics: Hit@1/3/5, MRR, nDCG@10, latency p50/p95, per category, plus a misses list for error analysis.
- **Alternatives:** LLM-generated questions (fast, but biased toward the generator's phrasing and needs a paid model); chunk-ID labels (break on every re-chunk).
- **Consequences:** + every later milestone is judged by numbers; labels survive re-chunking. − 175 questions written by one person reflect one person's phrasing; expand with real user questions after launch.

## ADR-009: Cross-encoder reranking over hybrid candidates
- **Date:** 2026-11-23 · **Status:** Accepted
- **Context:** RRF fusion helps recall but ranks by agreement, not by relevance to the exact question. Questions often differ from the rule's wording.
- **Decision:** Re-score the top 30 fused child chunks with `BAAI/bge-reranker-v2-m3` (fp16 on the GPU, ~1.1 GB), then group into parents. The ablation table in `evals/results/retrieval_report.md` must show it earns its latency.
- **Alternatives:** LLM reranking (slower, costs tokens); no reranking (simpler, lower precision at rank 1).
- **Consequences:** + higher Hit@1 / MRR, so the LLM sees the right rule first. − ~1.1 GB more VRAM (6 GB card: embedder + reranker + LLM is tight; `USE_RERANKER=false` turns it off) and extra latency per query.

## ADR-010: Streaming answers, deterministic citation self-check, refusal
- **Date:** 2026-11-23 · **Status:** Accepted
- **Context:** A 4B local model takes ~20-30 s to write a full answer; users abandon long silent waits. Small models also occasionally cite the wrong source or change a number.
- **Decision:** `/ask/stream` sends Server-Sent Events (sources first, then tokens, then a `done` event with timings). Every answer is checked by `app/citations.py`: cited sources must exist, sentences need citations, cited sentences' terms and **numbers** must appear in the cited sources. Out-of-scope questions get a fixed refusal; an optional rerank-score threshold refuses before calling the LLM.
- **Alternatives:** WebSockets (bidirectional, not needed); an LLM-judge on every request (doubles latency and cost; used offline in the M6 evals instead).
- **Consequences:** + time-to-first-word ~1-2 s, visible warnings on doubtful answers, no invented numbers going unnoticed. − the lexical check can flag correct paraphrases; it warns, it doesn't block.
