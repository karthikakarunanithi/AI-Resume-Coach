"""Thin driver around the compiled graph: start an interview, feed answers, get what the interviewer says.

Used by the CLI, the REST text API and the voice WebSocket.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.types import Command

from app.agents.state import InterviewConfig
from app.llm.schemas import AnswerEvaluation
from app.services.evaluator import BackgroundEvaluator

# Custom-stream events from the graph: {"type": "say_delta", "text": ...} and {"type": "say_end"}
OnEvent = Callable[[dict], Awaitable[None]]


@dataclass
class TurnResult:
    spoken: list[str]  # interviewer lines produced since the last call, in order
    done: bool
    question_id: str | None  # question the candidate is now answering
    question_number: int | None = None  # 1-based position of question_id in the plan
    total_questions: int | None = None
    time_left_s: int | None = None


class InterviewRunner:
    def __init__(self, graph: Any, session_id: str | None = None, evaluator: BackgroundEvaluator | None = None):
        self.graph = graph
        self.evaluator = evaluator
        self.session_id = session_id or str(uuid.uuid4())
        self.config = {"configurable": {"thread_id": self.session_id}}
        self._seen_turns = 0

    async def start(self, config: InterviewConfig, profile: dict | None = None, jd: dict | None = None) -> TurnResult:
        initial = {"session_id": self.session_id, "config": config, "profile": profile or {}, "jd": jd}
        await self.graph.ainvoke(initial, self.config)
        return await self._result()

    async def answer(self, text: str, end: bool = False, on_event: OnEvent | None = None) -> TurnResult:
        """Resume the graph with the candidate's answer. With on_event, interviewer speech is streamed
        (say_delta / say_end events) while the turn is still being generated."""
        command = Command(resume={"text": text, "end": end})
        if on_event is None:
            await self.graph.ainvoke(command, self.config)
        else:
            async for event in self.graph.astream(command, self.config, stream_mode="custom"):
                await on_event(event)
        return await self._result()

    async def state(self) -> dict:
        return (await self.graph.aget_state(self.config)).values

    async def evaluations(self) -> dict[str, AnswerEvaluation | None]:
        """Wait for all background evaluations (call after the interview is done)."""
        return await self.evaluator.results() if self.evaluator else {}

    async def _result(self) -> TurnResult:
        snapshot = await self.graph.aget_state(self.config)
        turns = snapshot.values.get("turns", [])
        if self.evaluator:
            plan = {q["id"]: q for q in snapshot.values.get("plan", [])}
            for qid in snapshot.values.get("finished_questions", []):
                self.evaluator.submit(plan[qid], turns)  # no-op if already submitted
        new = turns[self._seen_turns :]
        self._seen_turns = len(turns)
        spoken = [t["text"] for t in new if t["speaker"] == "interviewer"]
        interrupts = [i for task in snapshot.tasks for i in task.interrupts]
        values = snapshot.values
        question_id = interrupts[0].value["question_id"] if interrupts else None
        ids = [q["id"] for q in values.get("plan", [])]
        time_left = None
        if "started_at" in values:  # the graph's default clock is time.time
            time_left = max(0, round(values["time_budget_s"] - (time.time() - values["started_at"])))
        return TurnResult(
            spoken=spoken,
            done=not snapshot.next,
            question_id=question_id,
            question_number=ids.index(question_id) + 1 if question_id in ids else None,
            total_questions=len(ids) or None,
            time_left_s=time_left,
        )
