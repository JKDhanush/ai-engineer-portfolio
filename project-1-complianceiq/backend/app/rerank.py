"""Cross-encoder reranker (BAAI/bge-reranker-v2-m3), loaded lazily like the embedder.

A cross-encoder scores (question, passage) PAIRS: both texts go through the model together, so it sees
which words of the question each passage actually addresses. Much more accurate than vector similarity,
but ~30x slower per passage, which is why it only re-orders the top ~30 hybrid candidates.
"""

from functools import lru_cache

MODEL_NAME = "BAAI/bge-reranker-v2-m3"


@lru_cache(maxsize=1)
def get_reranker(device: str = "cuda"):
    import torch
    from sentence_transformers import CrossEncoder

    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    model = CrossEncoder(MODEL_NAME, device="cpu", max_length=512)
    if device == "cuda":
        model.model.half()       # fp16 on the CPU first, then move: avoids a VRAM spike (see ingest/embedder.py)
        model.model.to("cuda")
    return model


def rerank(query: str, passages: list[str], device: str = "cuda") -> list[float]:
    model = get_reranker(device)
    return [float(s) for s in model.predict([(query, p) for p in passages], batch_size=8, show_progress_bar=False)]
