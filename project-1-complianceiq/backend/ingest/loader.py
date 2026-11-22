"""Stage 5: write one document and its chunks into Postgres, in a single transaction."""

import json
from datetime import date

import asyncpg

from .chunker import Chunk
from .embedder import to_pgvector


async def document_exists(conn: asyncpg.Connection, content_hash: str) -> bool:
    return bool(await conn.fetchval("SELECT 1 FROM documents WHERE content_hash = $1", content_hash))


async def load_document(
    conn: asyncpg.Connection,
    *,
    content_hash: str,
    source_file: str,
    doc_type: str,
    circular_no: str | None,
    title: str,
    issued_on: date | None,
    status: str,
    metadata: dict,
    parents: list[Chunk],
    children: list[Chunk],
    child_embeddings: list[list[float]],
) -> int:
    """Replace any previous copy of the document, insert it, return the number of chunks written.

    One transaction: if anything fails half-way, nothing is written (no half-loaded documents).
    Deleting the document deletes its chunks too (ON DELETE CASCADE in the schema).
    """
    async with conn.transaction():
        await conn.execute("DELETE FROM documents WHERE content_hash = $1", content_hash)
        doc_id = await conn.fetchval(
            """INSERT INTO documents (source_file, content_hash, doc_type, circular_no, title, issued_on,
                                      status, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb) RETURNING id""",
            source_file, content_hash, doc_type, circular_no, title, issued_on, status, json.dumps(metadata),
        )
        parent_ids = []
        for p in parents:
            parent_ids.append(await conn.fetchval(
                """INSERT INTO chunks (document_id, chunk_level, chunk_index, section_path, page_start, page_end,
                                       context_header, content, token_count, content_hash, metadata)
                   VALUES ($1, 'parent', $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb) RETURNING id""",
                doc_id, p.index, p.section_path, p.page_start, p.page_end, p.context_header, p.content,
                p.token_count, p.content_hash, json.dumps(p.metadata),
            ))
        await conn.executemany(
            """INSERT INTO chunks (document_id, parent_id, chunk_level, chunk_index, section_path, page_start,
                                   page_end, context_header, content, token_count, content_hash, embedding, metadata)
               VALUES ($1, $2, 'child', $3, $4, $5, $6, $7, $8, $9, $10, $11::vector, $12::jsonb)""",
            [
                (doc_id, parent_ids[c.parent_index], c.index, c.section_path, c.page_start, c.page_end,
                 c.context_header, c.content, c.token_count, c.content_hash, to_pgvector(v), json.dumps(c.metadata))
                for c, v in zip(children, child_embeddings, strict=True)
            ],
        )
    return len(parents) + len(children)
