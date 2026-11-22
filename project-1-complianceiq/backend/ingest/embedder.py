"""Embeddings with BAAI/bge-m3 (ADR-005), shared by the ingest script and the API.

The model is imported lazily so that code which only *reads* chunks (or the slim Docker image)
doesn't need torch installed.
"""

from functools import lru_cache

MODEL_NAME = "BAAI/bge-m3"
DIM = 1024


@lru_cache(maxsize=1)
def get_model(device: str = "cuda"):
    import torch
    from sentence_transformers import SentenceTransformer

    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    # Load on the CPU, convert to fp16 there, THEN move to the GPU. Loading straight onto the GPU in fp32
    # (2.2 GB) and converting there briefly needs ~3.3 GB of VRAM, too much on a 6 GB card next to Ollama.
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    if device == "cuda":
        model.half()  # fp16: half the VRAM (~1.1 GB), ~2x faster, negligible quality loss
        model.to("cuda")
    return model


def embed(texts: list[str], batch_size: int = 16, device: str = "cuda", progress: bool = False) -> list[list[float]]:
    """Normalized embeddings, so cosine similarity = dot product (what pgvector's <=> uses)."""
    model = get_model(device)
    vecs = model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                        show_progress_bar=progress, convert_to_numpy=True)
    return vecs.tolist()


def to_pgvector(vec: list[float]) -> str:
    """pgvector's text format: '[0.1,0.2,...]'. We pass it as text and cast with ::vector in SQL."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
