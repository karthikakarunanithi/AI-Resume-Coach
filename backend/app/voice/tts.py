"""Text-to-speech (plan 8.3). "browser" sends text only and the client speaks it (free, no keys);
"litellm" synthesizes on the server (e.g. openai/tts-1) and streams audio per sentence."""

from functools import lru_cache
from typing import Any, Protocol

from litellm import aspeech

from app.config import load_models


class TextToSpeech(Protocol):
    mode: str  # "browser" or "server"
    mime: str | None

    async def synthesize(self, text: str) -> bytes | None: ...


class BrowserTTS:
    mode = "browser"
    mime = None

    async def synthesize(self, text: str) -> bytes | None:
        return None


class LiteLLMTTS:
    mode = "server"

    def __init__(self, model: str, voice: str = "alloy", response_format: str = "mp3"):
        self.model = model
        self.voice = voice
        self.response_format = response_format
        self.mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "opus": "audio/ogg", "aac": "audio/aac"}[response_format]

    async def synthesize(self, text: str) -> bytes | None:
        resp = await aspeech(model=self.model, input=text, voice=self.voice, response_format=self.response_format)
        return resp.content


def build_tts(cfg: dict[str, Any]) -> TextToSpeech:
    if cfg["provider"] == "browser":
        return BrowserTTS()
    if cfg["provider"] == "litellm":
        return LiteLLMTTS(cfg["model"], cfg.get("voice", "alloy"), cfg.get("response_format", "mp3"))
    raise ValueError(f"Unknown tts provider: {cfg['provider']}")


@lru_cache
def get_tts() -> TextToSpeech:
    return build_tts(load_models()["tts"])
