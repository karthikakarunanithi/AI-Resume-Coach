"""LangGraph interview agent (plan section 6).

plan_interview -> open_interview -> receive_answer -> guardrail -> summarize_context -> decide_next
                                        ^                 |                                  |
                                        +--- redirect ----+                                  |
                                        +------------ follow_up / clarify / next ------------+
guardrail / decide_next -> wrap_up -> END  (time up, plan finished, or candidate ended early)
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.guardrails import check_answer
from app.agents.planning import (
    MIX,
    QuestionRetriever,
    filters_for,
    finalize_plan,
    num_questions,
    plan_from_bank,
)
from app.agents.state import (
    MAX_FOLLOW_UPS,
    RECENT_TURNS,
    SUMMARIZE_EVERY,
    WRAP_UP_MARGIN_S,
    InterviewState,
    Turn,
)
from app.agents.streaming import read_interviewer_stream, text_chunks
from app.llm.client import LLMClient
from app.llm.schemas import CandidateProfile, InterviewerAction, InterviewPlan, JDAnalysis
from app.prompts import load_prompt, render_prompt
from app.rag.retriever import build_query

logger = logging.getLogger("coach.agent")

PLANNER_PROMPT = "planner_v1"
INTERVIEWER_PROMPT = "interviewer_v2"
SUMMARIZER_PROMPT = "summarizer_v1"
BANK_CANDIDATES = 20


def build_interview_graph(
    llm: LLMClient,
    retriever: QuestionRetriever | None = None,
    clock: Callable[[], float] = time.time,
    checkpointer: BaseCheckpointSaver | None = None,
):
    # session id -> summary being written in the background (see summarize_context)
    pending_summaries: dict[str, asyncio.Task[tuple[str, int] | None]] = {}

    def elapsed(state: InterviewState) -> float:
        return clock() - state["started_at"]

    def time_up(state: InterviewState) -> bool:
        return elapsed(state) >= state["time_budget_s"] - WRAP_UP_MARGIN_S

    def interviewer_turn(state: InterviewState, text: str, question_id: str | None) -> Turn:
        return {"speaker": "interviewer", "text": text, "question_id": question_id, "at_s": elapsed(state)}

    # --- nodes -----------------------------------------------------------------------------

    async def plan_interview(state: InterviewState) -> dict:
        cfg = state["config"]
        n = num_questions(cfg["duration_min"])
        profile = CandidateProfile.model_validate(state.get("profile") or {})
        jd = JDAnalysis.model_validate(state["jd"]) if state.get("jd") else None

        bank = []
        if retriever is not None:
            bank = await retriever.search(build_query(cfg["role"], jd, profile), filters_for(cfg), k=BANK_CANDIDATES)

        messages = [{"role": "user", "content": render_prompt(
            PLANNER_PROMPT,
            duration=cfg["duration_min"], interview_type=cfg["interview_type"], role=cfg["role"],
            difficulty=cfg["difficulty"], num_questions=n, mix=MIX[cfg["interview_type"]],
            profile_json=profile.model_dump_json(),
            jd_json=jd.model_dump_json() if jd else "None provided",
            bank_json=json.dumps(
                [{"text": q.text, "topic": q.topic, "difficulty": q.difficulty,
                  "ideal_key_points": q.ideal_key_points} for q in bank]
            ) if bank else "None available",
        )}]
        try:
            plan = finalize_plan((await llm.structured("planner", messages, InterviewPlan, prompt_version=PLANNER_PROMPT)).questions, n)
        except Exception:
            if not bank:
                raise
            logger.exception("Planner failed; falling back to top bank questions")
            plan = plan_from_bank(bank, n)

        return {
            "plan": plan, "current_q_index": 0, "follow_ups_on_current": 0, "status": "in_progress",
            "running_summary": "", "summarized_turns": 0, "end_requested": False,
            "started_at": clock(), "time_budget_s": cfg["duration_min"] * 60,
        }

    async def open_interview(state: InterviewState) -> dict:
        first = state["plan"][0]
        name = (state.get("profile") or {}).get("name")
        instruction = (
            f"Start the interview. Greet the candidate{' (' + first_name(name) + ')' if name else ''} in one short "
            f"sentence, then ask question {first['id']}: {first['text']}\n"
            f"ALLOWED ACTIONS: next_question (question_id {first['id']})"
        )
        action = await _interviewer(state, instruction, allowed={"next_question"})
        text = action.spoken_text if action else say(f"Hi, I'm Asha, and I'll be your interviewer today. {first['text']}")
        return {"turns": [interviewer_turn(state, text, first["id"])]}

    def receive_answer(state: InterviewState) -> dict:
        # Pauses the graph; the client resumes it with Command(resume={"text": ..., "end": bool})
        reply = interrupt({"question_id": _current(state)["id"], "interviewer": state["turns"][-1]["text"]})
        if isinstance(reply, str):
            reply = {"text": reply}
        text = (reply.get("text") or "").strip()
        update: dict[str, Any] = {"end_requested": bool(reply.get("end"))}
        if text:
            update["turns"] = [{
                "speaker": "candidate", "text": text, "question_id": _current(state)["id"], "at_s": elapsed(state),
            }]
        return update

    def guardrail(state: InterviewState) -> dict:
        result = check_answer(state["turns"][-1]["text"] if state["turns"][-1]["speaker"] == "candidate" else "")
        if result.safe:
            return {"last_answer_safe": True}
        logger.info("Guardrail triggered: %s", result.reason)
        return {
            "last_answer_safe": False,
            # A redirect uses up a follow-up, so repeated attempts can't stall the interview on one question
            "follow_ups_on_current": state["follow_ups_on_current"] + 1,
            "turns": [interviewer_turn(state, say(result.redirect), _current(state)["id"])],
        }

    async def summarize_context(state: InterviewState) -> dict:
        """Compresses older turns without making the candidate wait: the summary is written in a background
        task and applied on a later turn once it's ready. Until then the interviewer just sees the turns it
        would have covered (a slightly longer prompt), so nothing is lost."""
        sid = state["session_id"]
        update: dict[str, Any] = {}
        task = pending_summaries.get(sid)
        if task is not None and task.done():
            del pending_summaries[sid]
            if (result := task.result()) is not None:
                update = {"running_summary": result[0], "summarized_turns": result[1]}

        turns = state["turns"]
        covered = update.get("summarized_turns", state["summarized_turns"])
        cutoff = len(turns) - RECENT_TURNS
        if sid not in pending_summaries and cutoff - covered >= SUMMARIZE_EVERY:
            previous = update.get("running_summary", state["running_summary"])
            pending_summaries[sid] = asyncio.create_task(_summarize(previous, turns[covered:cutoff], cutoff))
        return update

    async def _summarize(previous: str, new_turns: list[Turn], cutoff: int) -> tuple[str, int] | None:
        messages = [
            {"role": "system", "content": load_prompt(SUMMARIZER_PROMPT)},
            {"role": "user", "content": f"CURRENT SUMMARY:\n{previous or '(none)'}\n\n"
                                        f"NEW TURNS:\n{_format_turns(new_turns)}"},
        ]
        try:
            resp = await llm.chat("summarizer", messages, prompt_version=SUMMARIZER_PROMPT)
            return resp.choices[0].message.content.strip(), cutoff
        except Exception:
            logger.exception("Summarizer failed; keeping previous summary")
            return None

    async def decide_next(state: InterviewState) -> dict:
        # Rules first (plan 6.4): predictable and free. The LLM only chooses among what the rules allow.
        if time_up(state):
            return {"status": "wrap_up"}
        idx = state["current_q_index"]
        current, nxt = state["plan"][idx], _next(state)
        allowed = {"next_question"} if nxt else {"wrap_up"}
        if state["follow_ups_on_current"] < MAX_FOLLOW_UPS:
            allowed |= {"follow_up", "clarify"}

        action = await _interviewer(state, _turn_instruction(state, allowed), allowed)
        if action is None:  # LLM failed or broke the rules: move on deterministically
            action = (
                InterviewerAction(action="next_question", spoken_text=say(f"Okay, thanks. {nxt['text']}"),
                                  question_id=nxt["id"], reason="fallback")
                if nxt else InterviewerAction(action="wrap_up", spoken_text="", reason="fallback")
            )

        if action.action == "wrap_up":
            return {"status": "wrap_up"}
        if action.action == "next_question":
            return {
                "current_q_index": idx + 1, "follow_ups_on_current": 0, "finished_questions": [current["id"]],
                "turns": [interviewer_turn(state, action.spoken_text, nxt["id"])],
            }
        return {
            "follow_ups_on_current": state["follow_ups_on_current"] + 1,
            "turns": [interviewer_turn(state, action.spoken_text, current["id"])],
        }

    def wrap_up(state: InterviewState) -> dict:
        if (task := pending_summaries.pop(state["session_id"], None)) is not None:
            task.cancel()  # nothing reads a summary after the last turn
        current_id = _current(state)["id"]
        answered = any(t["speaker"] == "candidate" and t["question_id"] == current_id for t in state["turns"])
        name = (state.get("profile") or {}).get("name")
        thanks = f"Thank you{', ' + first_name(name) if name else ''}"
        closing = (
            f"No problem, let's stop here. {thanks}. Your feedback report will cover the questions you answered."
            if state.get("end_requested")
            else f"That's all we have time for today. {thanks}, it was great talking with you. "
            "Your feedback report will be ready shortly."
        )
        return {
            "status": "done",
            "finished_questions": [current_id] if answered and current_id not in state.get("finished_questions", []) else [],
            "turns": [interviewer_turn(state, say(closing), None)],
        }

    # --- interviewer LLM call ---------------------------------------------------------------

    async def _interviewer(state: InterviewState, instruction: str, allowed: set[str]) -> InterviewerAction | None:
        messages = [
            {"role": "system", "content": _interviewer_system_prompt(state)},
            {"role": "user", "content": instruction},
        ]
        writer = get_stream_writer()
        try:
            stream = await llm.chat("interviewer", messages, stream=True, prompt_version=INTERVIEWER_PROMPT)
            action = await read_interviewer_stream(
                text_chunks(stream), allowed, lambda delta: writer({"type": "say_delta", "text": delta})
            )
        except ValueError as e:  # bad header or a disallowed action: rejected before anything was spoken
            logger.warning("Interviewer output rejected (%s); using fallback", e)
            return None
        except Exception:
            logger.exception("Interviewer LLM failed")
            return None
        writer({"type": "say_end"})
        if action.action != "wrap_up" and not action.spoken_text:
            return None
        return action

    # --- routing ----------------------------------------------------------------------------

    def after_guardrail(state: InterviewState) -> str:
        if state.get("end_requested") or time_up(state):
            return "wrap_up"
        return "summarize_context" if state["last_answer_safe"] else "receive_answer"

    def after_decide(state: InterviewState) -> str:
        return "wrap_up" if state["status"] == "wrap_up" else "receive_answer"

    g = StateGraph(InterviewState)
    for node in (plan_interview, open_interview, receive_answer, guardrail, summarize_context, decide_next, wrap_up):
        g.add_node(node.__name__, node)
    g.add_edge(START, "plan_interview")
    g.add_edge("plan_interview", "open_interview")
    g.add_edge("open_interview", "receive_answer")
    g.add_edge("receive_answer", "guardrail")
    g.add_conditional_edges("guardrail", after_guardrail, ["wrap_up", "summarize_context", "receive_answer"])
    g.add_edge("summarize_context", "decide_next")
    g.add_conditional_edges("decide_next", after_decide, ["wrap_up", "receive_answer"])
    g.add_edge("wrap_up", END)
    return g.compile(checkpointer=checkpointer)


# --- helpers ---------------------------------------------------------------------------------


def first_name(full_name: str) -> str:
    """"KARTHIKA K" (resumes often use capitals) -> "Karthika"; mixed case like "McKenzie" is kept as written."""
    first = full_name.split()[0]
    return first.capitalize() if first.isupper() or first.islower() else first


def say(text: str) -> str:
    """Emit a complete interviewer line on the custom stream (voice clients speak these events)."""
    writer = get_stream_writer()
    writer({"type": "say_delta", "text": text})
    writer({"type": "say_end"})
    return text


def _current(state: InterviewState) -> dict:
    return state["plan"][state["current_q_index"]]


def _next(state: InterviewState) -> dict | None:
    i = state["current_q_index"] + 1
    return state["plan"][i] if i < len(state["plan"]) else None


def _format_turns(turns: list[Turn]) -> str:
    return "\n".join(f"{t['speaker'].capitalize()}: {t['text']}" for t in turns)


def _interviewer_system_prompt(state: InterviewState) -> str:
    # Static for the whole session, so provider-side prompt caching applies (plan rule 5.3.6)
    cfg = state["config"]
    return render_prompt(
        INTERVIEWER_PROMPT,
        interview_type=cfg["interview_type"], role=cfg["role"], company_type=cfg["company_type"],
        difficulty=cfg["difficulty"], profile_summary=CandidateProfile.model_validate(state.get("profile") or {}).summary(),
        plan_json=json.dumps([{"id": q["id"], "topic": q["topic"], "text": q["text"]} for q in state["plan"]]),
    )


def _turn_instruction(state: InterviewState, allowed: set[str]) -> str:
    """Per-turn context: running summary + the turns it doesn't cover yet (RECENT_TURNS to
    RECENT_TURNS + SUMMARIZE_EVERY of them), never the whole transcript (plan rule 5.3.5)."""
    current, nxt = _current(state), _next(state)
    covered = state["summarized_turns"]
    minutes_left = max(0, (state["time_budget_s"] - (state["turns"][-1]["at_s"])) / 60)
    parts = []
    if state["running_summary"]:
        parts.append(f"SUMMARY OF EARLIER CONVERSATION:\n{state['running_summary']}")
    parts += [
        f"RECENT TURNS:\n{_format_turns(state['turns'][covered:])}",
        (f"CURRENT QUESTION ({current['id']}, follow-ups used {state['follow_ups_on_current']}/{MAX_FOLLOW_UPS}): "
        f"{current['text']}\nKey points a strong answer covers (never reveal): {'; '.join(current['ideal_key_points'])}"),
        f"NEXT PLANNED QUESTION ({nxt['id']}): {nxt['text']}" if nxt else "NEXT PLANNED QUESTION: none, this is the last one.",
        f"TIME LEFT: about {minutes_left:.0f} minutes",
        f"ALLOWED ACTIONS: {', '.join(sorted(allowed))}",
    ]
    return "\n\n".join(parts)
