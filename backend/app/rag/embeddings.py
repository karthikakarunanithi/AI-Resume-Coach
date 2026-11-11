import asyncio
from functools import lru_cache
from typing import Any, Protocol

from litellm import aembedding

from app.config import load_models


class Embedder(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    """sentence-transformers model run in-process (default: BAAI/bge-m3, 1024-d)."""

    def __init__(self, model: str, dim: int, batch_size: int = 32):
        from sentence_transformers import SentenceTransformer  # optional dependency, heavy import

        self.model = SentenceTransformer(model)
        self.dim = dim
        self.batch_size = batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await asyncio.to_thread(
            self.model.encode, texts, batch_size=self.batch_size, normalize_embeddings=True
        )
        return vectors.tolist()


class LiteLLMEmbedder:
    """Hosted embedding API through LiteLLM (e.g. openai/text-embedding-3-small with dimensions=1024)."""

    def __init__(self, model: str, dim: int, batch_size: int = 100):
        self.model = model
        self.dim = dim
        self.batch_size = batch_size

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            resp = await aembedding(model=self.model, input=texts[i : i + self.batch_size], dimensions=self.dim)
            out.extend(item["embedding"] for item in resp.data)
        return out


def build_embedder(cfg: dict[str, Any]) -> Embedder:
    kwargs = {"model": cfg["model"], "dim": cfg["dim"], "batch_size": cfg.get("batch_size", 32)}
    if cfg["provider"] == "local":
        return LocalEmbedder(**kwargs)
    if cfg["provider"] == "litellm":
        return LiteLLMEmbedder(**kwargs)
    raise ValueError(f"Unknown embeddings provider: {cfg['provider']}")


@lru_cache
def get_embedder() -> Embedder:
    return build_embedder(load_models()["embeddings"])
