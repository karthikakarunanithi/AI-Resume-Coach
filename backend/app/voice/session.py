"""One live voice interview over a socket: audio in -> STT -> agent -> streamed text + sentence-level TTS out.

Transport-agnostic (anything with send_json / send_bytes), so it is tested without a real WebSocket.

Server -> client messages (plan 12):
  ready            {tts: "server"|"browser", question_id, question_number, total_questions, time_left_s}
  status           {state: "transcribing"|"thinking"}
  transcript_final {text}
  no_speech        {}
  ai_text_delta    {text}                         live captions as the reply streams
  ai_sentence      {seq, text}                    a complete sentence; "browser" TTS speaks this
  ai_audio         {seq, mime} + one binary frame "server" TTS audio for that sentence
  ai_audio_failed  {seq}                          server TTS failed; speak the text instead
  turn_end         {question_id, done, question_number, total_questions, time_left_s}
  interview_end    {session_id}
  error            {message}
"""

import asyncio
import logging
import time
import uuid
from typing import Protocol

from app.services.interviews import InterviewManager
from app.voice.sentences import SentenceBuffer
from app.voice.speech_metrics import utterance_metrics
from app.voice.stt import SpeechToText, stt_prompt
from app.voice.tts import TextToSpeech

logger = logging.getLogger("coach.voice")

MAX_UTTERANCE_BYTES = 10 * 1024 * 1024  # ~5 minutes of 16 kHz 16-bit mono WAV


class Socket(Protocol):
    async def send_json(self, data: dict) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...


class Speaker:
    """Turns say_delta/say_end events into captions + ordered per-sentence TTS, without blocking the LLM stream."""

    def __init__(self, ws: Socket, tts: TextToSpeech, first_seq: int = 0, timing: dict | None = None):
        self.ws = ws
        self.tts = tts
        self.seq = first_seq
        self.timing = timing  # gets first_sentence_ms / first_audio_ms (relative to timing["t0"])
        self.buffer = SentenceBuffer()
        self.queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
        self.worker = asyncio.create_task(self._work())

    async def on_event(self, event: dict) -> None:
        if event.get("type") == "say_delta":
            await self.ws.send_json({"type": "ai_text_delta", "text": event["text"]})
            for sentence in self.buffer.push(event["text"]):
                self._enqueue(sentence)
        elif event.get("type") == "say_end" and (rest := self.buffer.flush()):
            self._enqueue(rest)

    async def say(self, text: str) -> None:
        await self.on_event({"type": "say_delta", "text": text})
        await self.on_event({"type": "say_end"})

    async def close(self) -> int:
        """Wait until every queued sentence was sent; returns the next sequence number."""
        if rest := self.buffer.flush():
            self._enqueue(rest)
        await self.queue.put(None)
        await self.worker
        return self.seq

    def _enqueue(self, sentence: str) -> None:
        self.queue.put_nowait((self.seq, sentence))
        self.seq += 1

    async def _work(self) -> None:
        while (item := await self.queue.get()) is not None:
            seq, text = item
            await self.ws.send_json({"type": "ai_sentence", "seq": seq, "text": text})
            self._mark("first_sentence_ms")
            if self.tts.mode != "server":
                continue
            try:
                audio = await self.tts.synthesize(text)
            except Exception:
                logger.exception("TTS failed for sentence %d", seq)
                audio = None
            if audio:
                await self.ws.send_json({"type": "ai_audio", "seq": seq, "mime": self.tts.mime})
                await self.ws.send_bytes(audio)
                self._mark("first_audio_ms")
            else:
                await self.ws.send_json({"type": "ai_audio_failed", "seq": seq})


    def _mark(self, key: str) -> None:
        if self.timing is not None and key not in self.timing:
            self.timing[key] = round((time.perf_counter() - self.timing["t0"]) * 1000, 1)


class VoiceSession:
    def __init__(
        self, ws: Socket, manager: InterviewManager, user_id: uuid.UUID, session_id: uuid.UUID,
        stt: SpeechToText, tts: TextToSpeech,
    ):
        self.ws, self.manager, self.stt, self.tts = ws, manager, stt, tts
        self.user_id, self.session_id = user_id, session_id
        self.question_id: str | None = None
        self.prompt = ""
        self.seq = 0
        self.done = False

    async def open(self) -> None:
        """Raises InterviewNotActiveError if the interview isn't running."""
        state = await self.manager.active_state(self.user_id, self.session_id)
        self.prompt = stt_prompt(state.get("profile"))
        self.question_id = state["plan"][state["current_q_index"]]["id"]
        progress = {
            "question_id": self.question_id, "question_number": state["current_q_index"] + 1,
            "total_questions": len(state["plan"]),
            "time_left_s": max(0, round(state["time_budget_s"] - (time.time() - state["started_at"]))),
        }
        await self.ws.send_json({"type": "ready", "tts": self.tts.mode, **progress})
        # The opening line was generated when the session was created; speak it now if nothing was answered yet
        if not any(t["speaker"] == "candidate" for t in state["turns"]):
            speaker = Speaker(self.ws, self.tts, self.seq)
            await speaker.say(state["turns"][-1]["text"])
            self.seq = await speaker.close()
        await self.ws.send_json({"type": "turn_end", "done": False, **progress})

    async def handle_audio(self, audio: bytes) -> None:
        if len(audio) > MAX_UTTERANCE_BYTES:
            await self._error("That answer was too long to process. Please answer in shorter parts.")
            return
        await self.ws.send_json({"type": "status", "state": "transcribing"})
        t0 = time.perf_counter()
        try:
            transcript = await self.stt.transcribe(audio, self.prompt)
        except Exception:
            logger.exception("STT failed")
            await self._error("Sorry, I couldn't process that audio. Please repeat, or type your answer.")
            return
        await self.ws.send_json({"type": "transcript_final", "text": transcript.text})
        if not transcript.text.strip():
            await self.ws.send_json({"type": "no_speech"})
            return
        timing = {"t0": t0, "mode": "voice", "stt_ms": round((time.perf_counter() - t0) * 1000, 1)}
        await self._turn(transcript.text, speech=utterance_metrics(transcript, self.question_id), timing=timing)

    async def handle_text(self, text: str) -> None:
        if text.strip():
            await self._turn(text.strip(), timing={"t0": time.perf_counter(), "mode": "text"})

    async def handle_end(self) -> None:
        await self._turn("", end=True)

    async def _turn(self, text: str, end: bool = False, speech=None, timing: dict | None = None) -> None:
        """timing: latency record for this turn, measured from when the answer arrived (t0); see TurnTiming."""
        if self.done:
            return
        await self.ws.send_json({"type": "status", "state": "thinking"})
        if timing is not None:
            timing["question_id"] = self.question_id
        speaker = Speaker(self.ws, self.tts, self.seq, timing)
        try:
            result = await self.manager.answer(
                self.user_id, self.session_id, text, end=end, on_event=speaker.on_event, speech=speech, timing=timing,
            )
        finally:
            self.seq = await speaker.close()
        if timing is not None:
            timing["turn_ms"] = round((time.perf_counter() - timing["t0"]) * 1000, 1)
        self.question_id, self.done = result.question_id, result.done
        await self.ws.send_json({
            "type": "turn_end", "question_id": result.question_id, "done": result.done,
            "question_number": result.question_number, "total_questions": result.total_questions,
            "time_left_s": result.time_left_s,
        })
        if result.done:
            await self.ws.send_json({"type": "interview_end", "session_id": str(self.session_id)})

    async def _error(self, message: str) -> None:
        await self.ws.send_json({"type": "error", "message": message})
