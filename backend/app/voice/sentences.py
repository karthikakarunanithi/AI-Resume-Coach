"""Splits streamed LLM text into sentences so each can go to TTS as soon as it's complete (plan 8.3)."""

import re

# A sentence ends at . ! ? (optionally followed by a closing quote/bracket) and then whitespace.
_BOUNDARY = re.compile(r"""[.!?]+["')\]]?\s+""")
_ABBREVIATIONS = ("e.g.", "i.e.", "vs.", "etc.", "dr.", "mr.", "ms.", "approx.")


class SentenceBuffer:
    def __init__(self) -> None:
        self._buf = ""

    def push(self, delta: str) -> list[str]:
        """Add streamed text; return any sentences that are now complete."""
        self._buf += delta
        out = []
        start = 0
        for m in _BOUNDARY.finditer(self._buf):
            candidate = self._buf[start : m.end()].strip()
            if candidate.lower().endswith(_ABBREVIATIONS):
                continue
            out.append(candidate)
            start = m.end()
        self._buf = self._buf[start:]
        return out

    def flush(self) -> str | None:
        rest, self._buf = self._buf.strip(), ""
        return rest or None
