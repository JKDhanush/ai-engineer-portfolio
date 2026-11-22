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
