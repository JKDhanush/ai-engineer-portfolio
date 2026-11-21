# ComplianceIQ — Architecture

```mermaid
flowchart LR
    subgraph Ingestion [Ingestion pipeline - offline]
        PDF[RBI/SEBI PDFs] --> Parse[Layout-aware parse<br/>text + tables]
        Parse --> Meta[Metadata extraction<br/>circular no, date, supersedes]
        Meta --> Chunk[Parent-child chunking<br/>+ contextual headers]
        Chunk --> Embed[Embed child chunks]
    end

    Embed --> PG[(Postgres<br/>pgvector HNSW + tsvector GIN)]

    subgraph Query [Query path - online]
        U[User] --> API[FastAPI]
        API --> Cache{Redis<br/>semantic cache}
        Cache -- miss --> QI[Query rewrite / multi-query / HyDE / router]
        QI --> H[Hybrid search<br/>BM25-style + vector]
        H --> PG
        H --> RRF[RRF fusion] --> RR[Cross-encoder rerank]
        RR --> Parent[Fetch parent chunks]
        Parent --> LLM[LLM gateway<br/>Bedrock + fallback]
        LLM --> Check[Citation self-check]
        Check -- SSE stream --> U
    end
```

## Components (M0 state)
| Component | Tech | Status |
|---|---|---|
| API | FastAPI (async), uvicorn | `/health` ✅ |
| Store | Postgres 17 + pgvector: `documents`, `chunks` (HNSW cosine, weighted tsvector GIN) | schema ✅ |
| Cache | Redis 7 | connected ✅ |
| Ingestion, retrieval, generation | — | M1–M5 |

## Key data model ideas
- **Parent-child chunks:** small child chunks give precise retrieval; their larger parent gives the LLM enough context.
- **Contextual header:** each chunk is prefixed with "Circular X, dated Y, section Z" before embedding, so a chunk that says only "the above limit" still carries its context.
- **Version graph:** `documents.supersedes` and `status` let answers flag superseded rules.
