"""Speech-to-text (plan 8.1): hosted Whisper via LiteLLM (default: Groq) or local faster-whisper."""

import asyncio
import io
import wave
from functools import lru_cache
from typing import Any, Protocol

from litellm import atranscription

from app.config import load_models
from app.llm.schemas import CandidateProfile
from app.voice.speech_metrics import Transcript, Word

# Whisper drops disfluencies unless the prompt contains some, which would hide filler words from the analytics
FILLER_PRIMER = "Um, so, uh, I mean, like, you know, I think... hmm, okay."
MAX_PROMPT_TERMS = 40


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes, prompt: str = "") -> Transcript: ...


def stt_prompt(profile: dict | None) -> str:
    """Bias recognition toward the candidate's own tech vocabulary (e.g. "FastAPI, LangGraph")."""
    p = CandidateProfile.model_validate(profile or {})
    terms = list(dict.fromkeys(p.skills + [t for pr in p.projects for t in pr.tech_stack]))[:MAX_PROMPT_TERMS]
    return f"{FILLER_PRIMER} {', '.join(terms)}." if terms else FILLER_PRIMER


def wav_duration(audio: bytes) -> float | None:
    try:
        with wave.open(io.BytesIO(audio)) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError):
        return None


class LiteLLMSTT:
    def __init__(self, model: str, language: str = "en"):
        self.model = model
        self.language = language

    async def transcribe(self, audio: bytes, prompt: str = "") -> Transcript:
        resp = await atranscription(
            model=self.model, file=("answer.wav", audio), prompt=prompt or None, language=self.language,
            response_format="verbose_json",
            # Sent as extra_body: LiteLLM's Groq integration rejects timestamp_granularities as a named parameter
            # ("Setting user/encoding format is not supported by groq"), though the Groq API supports it
            extra_body={"timestamp_granularities": ["word", "segment"]},
        )
        words = [Word(w["word"].strip(), float(w["start"]), float(w["end"])) for w in (_get(resp, "words") or [])]
        duration = _get(resp, "duration")
        duration_s = float(duration) if duration else wav_duration(audio)
        segments = _get(resp, "segments")
        if not segments:  # provider gave no per-segment confidence: nothing to filter on
            return Transcript(text=(resp.text or "").strip(), words=words, duration_s=duration_s)
        kept = [s for s in segments if is_real_speech(s.get("no_speech_prob", 0.0), s.get("avg_logprob", 0.0))]
        return Transcript(
            text=" ".join(s["text"].strip() for s in kept).strip(),
            words=[w for w in words if any(s["start"] <= w.start < s["end"] for s in kept)],
            duration_s=duration_s,
        )


class LocalWhisperSTT:
    """faster-whisper in-process (pip install -e ".[voice]"). Use distil-large-v3 or large-v3 for accuracy."""

    def __init__(self, model: str, device: str = "auto", compute_type: str = "default", language: str = "en"):
        from faster_whisper import WhisperModel  # optional dependency

        self.model = WhisperModel(model, device=device, compute_type=compute_type)
        self.language = language

    async def transcribe(self, audio: bytes, prompt: str = "") -> Transcript:
        return await asyncio.to_thread(self._transcribe, audio, prompt)

    def _transcribe(self, audio: bytes, prompt: str) -> Transcript:
        segments, info = self.model.transcribe(
            io.BytesIO(audio), language=self.language, beam_size=1, word_timestamps=True,
            initial_prompt=prompt or None, vad_filter=True,
            # don't let one hallucinated segment seed the next
            condition_on_previous_text=False, hallucination_silence_threshold=1.0,
        )
        # transcription runs lazily while iterating
        segments = [s for s in segments if is_real_speech(s.no_speech_prob, s.avg_logprob)]
        words = [Word(w.word.strip(), float(w.start), float(w.end)) for s in segments for w in (s.words or [])]
        return Transcript(text=" ".join(s.text.strip() for s in segments).strip(), words=words,
                          duration_s=info.duration)


def is_real_speech(no_speech_prob: float, avg_logprob: float) -> bool:
    """Whisper invents text ("Thank you.", "Thanks for watching") on trailing silence or noise. Those segments
    have low confidence: on a real recording, speech scored avg_logprob -0.12 and hallucinations -1.3 to -2.1."""
    if avg_logprob < -1.0:
        return False
    return not (no_speech_prob > 0.5 and avg_logprob < -0.6)


def _get(resp: Any, key: str) -> Any:
    value = getattr(resp, key, None)
    if value is None and hasattr(resp, "get"):
        value = resp.get(key)
    return value


def build_stt(cfg: dict[str, Any]) -> SpeechToText:
    if cfg["provider"] == "litellm":
        return LiteLLMSTT(cfg["model"], cfg.get("language", "en"))
    if cfg["provider"] == "local":
        return LocalWhisperSTT(cfg["model"], cfg.get("device", "auto"), cfg.get("compute_type", "default"),
                               cfg.get("language", "en"))
    raise ValueError(f"Unknown stt provider: {cfg['provider']}")


@lru_cache
def get_stt() -> SpeechToText:
    return build_stt(load_models()["stt"])
