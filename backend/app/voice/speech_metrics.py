"""Speech analytics from transcripts and word timestamps (plan 8.2) — plain Python, no LLM."""

import re
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel

LONG_PAUSE_S = 2.0
SHORT_ANSWER_S = 15
LONG_ANSWER_S = 180
SLOW_WPM, FAST_WPM = 110, 170

# Only unambiguous fillers: "like" and "so" are counted just in their filler positions,
# since "I'd like to" or "so that" are normal speech.
FILLER_PATTERNS = {
    "um": r"\b(um+|umm+|erm+)\b",
    "uh": r"\b(uh+|uhh+)\b",
    "hmm": r"\bhmm+\b",
    "you know": r"\byou know\b(?! (how|what|why|when|where|that|the|a|it))",
    "i mean": r"\bi mean\b(?! (that|the|a|it|to))",
    "basically": r"\bbasically\b",
    "actually": r"\bactually\b",
    "like": r"\blike,",
    "so": r"(^|[.!?]\s+)so,",
}
HEDGE_PATTERNS = [
    r"\bi'?m not (really |fully |totally )?sure\b", r"\bnot sure\b", r"\bmaybe\b", r"\bi guess\b",
    r"\bprobably\b", r"\bperhaps\b", r"\bi think maybe\b", r"\bkind of\b", r"\bsort of\b",
]
_FILLER_RES = {name: re.compile(p, re.IGNORECASE) for name, p in FILLER_PATTERNS.items()}
_HEDGE_RE = re.compile("|".join(HEDGE_PATTERNS), re.IGNORECASE)


@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class Transcript:
    text: str
    words: list[Word] = field(default_factory=list)
    duration_s: float | None = None  # length of the audio clip


class UtteranceMetrics(BaseModel):
    question_id: str | None = None
    words: int
    speaking_s: float
    wpm: float | None
    fillers: dict[str, int]
    hedges: int
    long_pauses: int
    longest_pause_s: float


def count_fillers(text: str) -> dict[str, int]:
    counts = {name: len(rx.findall(text)) for name, rx in _FILLER_RES.items()}
    return {k: v for k, v in counts.items() if v}


def utterance_metrics(t: Transcript, question_id: str | None = None) -> UtteranceMetrics:
    n_words = len(re.findall(r"[\w']+", t.text))
    if len(t.words) >= 2:
        speaking = t.words[-1].end - t.words[0].start
        gaps = [b.start - a.end for a, b in zip(t.words, t.words[1:], strict=False)]
    else:
        speaking = t.duration_s or 0.0
        gaps = []
    long_gaps = [g for g in gaps if g > LONG_PAUSE_S]
    return UtteranceMetrics(
        question_id=question_id, words=n_words, speaking_s=round(speaking, 2),
        wpm=round(n_words / speaking * 60, 1) if speaking >= 1 else None,
        fillers=count_fillers(t.text), hedges=len(_HEDGE_RE.findall(t.text)),
        long_pauses=len(long_gaps), longest_pause_s=round(max(gaps, default=0.0), 2),
    )


class SpeechSummary(BaseModel):
    avg_wpm: float | None
    pace: str | None  # slow | good | fast
    total_words: int
    fillers_per_100_words: float
    filler_counts: dict[str, int]
    hedges: int
    long_pauses: int
    answer_seconds: dict[str, float]  # question_id -> total speaking time
    flags: list[str]


def summarize_speech(utterances: list[UtteranceMetrics]) -> SpeechSummary | None:
    if not utterances:
        return None
    words = sum(u.words for u in utterances)
    timed = [u for u in utterances if u.wpm is not None]
    seconds = sum(u.speaking_s for u in timed)
    wpm = round(sum(u.words for u in timed) / seconds * 60, 1) if seconds >= 1 else None
    fillers: Counter[str] = Counter()
    per_question: Counter[str] = Counter()
    for u in utterances:
        fillers.update(u.fillers)
        if u.question_id:
            per_question[u.question_id] += u.speaking_s

    flags = []
    if wpm is not None and wpm < SLOW_WPM:
        flags.append(f"Pace is slow ({wpm:.0f} wpm); aim for 120-160.")
    if wpm is not None and wpm > FAST_WPM:
        flags.append(f"Pace is fast ({wpm:.0f} wpm); slow down so key points land.")
    per_100 = round(sum(fillers.values()) / words * 100, 1) if words else 0.0
    if per_100 > 3:
        flags.append(f"{per_100} filler words per 100 words; pause silently instead.")
    flags += [f"{q}: very short answer ({s:.0f}s)." for q, s in per_question.items() if s < SHORT_ANSWER_S]
    flags += [f"{q}: long answer ({s / 60:.1f} min); lead with the main point." for q, s in per_question.items()
              if s > LONG_ANSWER_S]

    return SpeechSummary(
        avg_wpm=wpm, pace=None if wpm is None else "slow" if wpm < SLOW_WPM else "fast" if wpm > FAST_WPM else "good",
        total_words=words, fillers_per_100_words=per_100, filler_counts=dict(fillers.most_common()),
        hedges=sum(u.hedges for u in utterances), long_pauses=sum(u.long_pauses for u in utterances),
        answer_seconds={q: round(s, 1) for q, s in per_question.items()}, flags=flags,
    )
