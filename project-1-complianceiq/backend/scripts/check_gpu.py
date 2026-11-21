"""Sanity check: is torch using the GPU, and does bge-m3 load and embed correctly?

Run from backend/ with the venv active:   python scripts/check_gpu.py
First run downloads bge-m3 (~2.2 GB) into ~/.cache/huggingface.
"""

import time

import torch
from sentence_transformers import SentenceTransformer

print(f"torch {torch.__version__} | CUDA available: {torch.cuda.is_available()}")
if not torch.cuda.is_available():
    raise SystemExit("No CUDA: torch is CPU-only. Tell Claude the output above.")

props = torch.cuda.get_device_properties(0)
print(f"GPU: {props.name} | VRAM: {props.total_memory / 1024**3:.1f} GB")

t0 = time.perf_counter()
model = SentenceTransformer("BAAI/bge-m3", device="cuda")
model.half()  # fp16: half the VRAM, ~2x faster, negligible quality loss for embeddings
print(f"bge-m3 loaded in {time.perf_counter() - t0:.1f}s | dim = {model.get_sentence_embedding_dimension()}")

texts = [
    "Banks must update KYC of high-risk customers at least once every two years.",
    "Periodic updation of KYC for high risk customers is required every 2 years.",
    "The repo rate was kept unchanged at the monetary policy meeting.",
]
emb = model.encode(texts, normalize_embeddings=True, batch_size=32)
sim = emb @ emb.T  # vectors are normalized, so dot product = cosine similarity
print(f"similar pair   (KYC vs KYC):  {sim[0, 1]:.3f}  <- should be high (~0.8+)")
print(f"unrelated pair (KYC vs repo): {sim[0, 2]:.3f}  <- should be much lower")
print(f"VRAM used: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
