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
