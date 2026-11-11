import hashlib
import math
import re


class HashingEmbedder:
    """Deterministic bag-of-words embedder: texts sharing words get similar vectors. No model download."""

    dim = 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def stream_text(text: str, piece: int = 7):
    """Mimic a LiteLLM streaming response: async iterator of chunks with choices[0].delta.content."""
    from types import SimpleNamespace

    async def gen():
        for i in range(0, len(text), piece):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text[i : i + piece]))])

    return gen()


def render_action(action) -> str:
    """InterviewerAction -> the streamed interviewer_v2 format."""
    return f"ACTION {action.action} {action.question_id or ''}\n{action.spoken_text}"
