import io
import wave

import pytest

from app.agents.streaming import ActionNotAllowedError, read_interviewer_stream
from app.voice.sentences import SentenceBuffer
from app.voice.speech_metrics import Transcript, Word, count_fillers, summarize_speech, utterance_metrics
from app.voice.stt import FILLER_PRIMER, is_real_speech, stt_prompt, wav_duration


def test_sentence_buffer_emits_complete_sentences_only():
    buf = SentenceBuffer()
    assert buf.push("Got it. What re") == ["Got it."]
    assert buf.push("call did you get, e.g. at k=5? And ") == ["What recall did you get, e.g. at k=5?"]
    assert buf.push("the latency was 3.5 seconds") == []
    assert buf.flush() == "And the latency was 3.5 seconds"
    assert buf.flush() is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Um, so I used, uh, FastAPI. You know, it's basically async.", {"um": 1, "uh": 1, "you know": 1, "basically": 1}),
        ("So, the model was like, really slow.", {"so": 1, "like": 1}),
        # not fillers: normal uses of these words
        ("I'd like to add caching so that latency drops. You know how Redis works.", {}),
    ],
)
def test_filler_counting(text, expected):
    assert count_fillers(text) == expected


def test_utterance_metrics_from_word_timestamps():
    words = [Word("I", 0.0, 0.2), Word("used", 0.3, 0.6), Word("Redis", 3.5, 4.0), Word("maybe", 4.1, 6.0)]
    m = utterance_metrics(Transcript("I used Redis maybe", words, duration_s=7.0), "q1")
    assert (m.words, m.speaking_s, m.long_pauses, m.longest_pause_s) == (4, 6.0, 1, 2.9)
    assert m.wpm == 40.0 and m.hedges == 1 and m.question_id == "q1"


def test_utterance_metrics_without_timestamps_uses_audio_length():
    m = utterance_metrics(Transcript("one two three four five", [], duration_s=2.0))
    assert m.wpm == 150.0 and m.long_pauses == 0


def test_speech_summary_flags():
    fast = utterance_metrics(Transcript(" ".join(["word"] * 100) + " um um um um", [], duration_s=30), "q1")
    short = utterance_metrics(Transcript("Yes I did that", [], duration_s=5), "q2")
    s = summarize_speech([fast, short])
    assert s.pace == "fast" and s.filler_counts == {"um": 4}
    assert s.answer_seconds == {"q1": 30.0, "q2": 5.0}
    assert any("q2: very short answer" in f for f in s.flags)
    assert any("filler words per 100 words" in f for f in s.flags)
    assert summarize_speech([]) is None


def test_stt_prompt_includes_candidate_vocabulary():
    prompt = stt_prompt({"skills": ["FastAPI", "LangGraph"], "projects": [{"title": "x", "tech_stack": ["pgvector", "FastAPI"]}]})
    assert prompt.startswith(FILLER_PRIMER) and prompt.endswith("FastAPI, LangGraph, pgvector.")
    assert stt_prompt(None) == FILLER_PRIMER


def test_wav_duration():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 24000)
    assert wav_duration(buf.getvalue()) == 1.5
    assert wav_duration(b"not a wav") is None


async def chunks(*parts, fail_after: int | None = None):
    for i, p in enumerate(parts):
        if fail_after is not None and i == fail_after:
            raise ConnectionError("stream dropped")
        yield p


async def test_stream_parser_header_split_across_chunks():
    emitted = []
    action = await read_interviewer_stream(
        chunks("ACT", "ION follow_", "up q2\nWhat ", "recall did you get?"), {"follow_up"}, emitted.append
    )
    assert (action.action, action.question_id) == ("follow_up", "q2")
    assert "".join(emitted) == "What recall did you get?" == action.spoken_text


async def test_stream_parser_rejects_disallowed_action_before_speaking():
    emitted = []
    with pytest.raises(ActionNotAllowedError):
        await read_interviewer_stream(chunks("ACTION follow_up q1\n", "More?"), {"next_question"}, emitted.append)
    assert emitted == []


async def test_stream_parser_rejects_json_output():
    with pytest.raises(ValueError, match="Bad ACTION header"):
        await read_interviewer_stream(chunks('{"action": "follow_up"}\n'), {"follow_up"}, lambda d: None)


async def test_stream_parser_keeps_partial_text_if_stream_drops():
    emitted = []
    action = await read_interviewer_stream(
        chunks("ACTION clarify q1\nLet me rephrase. ", "What would", " you", fail_after=2), {"clarify"}, emitted.append
    )
    assert action.spoken_text == "Let me rephrase. What would"


async def test_stream_parser_error_before_text_propagates():
    with pytest.raises(ConnectionError):
        await read_interviewer_stream(chunks("ACTION clarify q1\n", "never sent", fail_after=1), {"clarify"}, lambda d: None)


@pytest.mark.parametrize(
    ("no_speech", "logprob", "real"),
    [(0.0, -0.12, True), (0.42, -2.07, False), (0.55, -1.27, False), (0.6, -0.7, False), (0.6, -0.3, True)],
)
def test_is_real_speech(no_speech, logprob, real):
    assert is_real_speech(no_speech, logprob) is real


async def test_hosted_stt_drops_hallucinated_segments(monkeypatch):
    from types import SimpleNamespace

    from app.voice import stt as stt_mod

    async def fake_atranscription(**kwargs):
        assert kwargs["extra_body"] == {"timestamp_granularities": ["word", "segment"]}
        assert "timestamp_granularities" not in kwargs  # LiteLLM's Groq integration rejects it as a named param
        return SimpleNamespace(
            text="I used Redis. Thank you.",
            duration=4.0,
            words=[{"word": "I", "start": 0.0, "end": 0.2}, {"word": "used", "start": 0.3, "end": 0.6},
                   {"word": "Redis.", "start": 0.7, "end": 1.2}, {"word": "Thank", "start": 3.0, "end": 3.3},
                   {"word": "you.", "start": 3.3, "end": 3.6}],
            segments=[{"start": 0.0, "end": 1.3, "text": " I used Redis.", "no_speech_prob": 0.01, "avg_logprob": -0.2},
                      {"start": 2.9, "end": 3.7, "text": " Thank you.", "no_speech_prob": 0.6, "avg_logprob": -1.4}],
        )

    monkeypatch.setattr(stt_mod, "atranscription", fake_atranscription)
    t = await stt_mod.LiteLLMSTT("groq/whisper-large-v3-turbo").transcribe(b"RIFF")
    assert t.text == "I used Redis."
    assert [w.word for w in t.words] == ["I", "used", "Redis."]
