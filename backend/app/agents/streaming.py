"""Streaming interviewer output: "ACTION <action> <question_id>" on line 1, then the spoken text.

The action is parsed and checked against the allowed set *before* any text is emitted, so a reply the
rules reject is never spoken. Spoken text then streams out delta by delta for sentence-level TTS.
"""

import re
from collections.abc import AsyncIterator, Callable

from app.llm.schemas import InterviewerAction

_HEADER = re.compile(r"^[`\s*]*ACTION[:\s]+(follow_up|clarify|next_question|wrap_up)\b[ \t]*(\S+)?", re.IGNORECASE)
MAX_HEADER_CHARS = 200


class ActionNotAllowedError(ValueError):
    pass


async def read_interviewer_stream(
    chunks: AsyncIterator[str], allowed: set[str], emit: Callable[[str], None]
) -> InterviewerAction:
    """Consume the stream, emitting spoken-text deltas. Raises ValueError for a bad or disallowed header.

    If the stream fails after text was emitted, the partial action is returned: those words were already
    spoken, so the transcript should record them.
    """
    header_buf = ""
    action: str | None = None
    question_id: str | None = None
    spoken: list[str] = []
    try:
        async for chunk in chunks:
            if action is None:
                header_buf += chunk
                if "\n" not in header_buf:
                    if len(header_buf) > MAX_HEADER_CHARS:
                        raise ValueError(f"No ACTION header: {header_buf[:80]!r}")
                    continue
                line, rest = header_buf.split("\n", 1)
                m = _HEADER.match(line)
                if not m:
                    raise ValueError(f"Bad ACTION header: {line[:80]!r}")
                action, question_id = m.group(1).lower(), (m.group(2) or None)
                if action not in allowed:
                    raise ActionNotAllowedError(f"{action} not in {sorted(allowed)}")
                chunk = rest.lstrip()
            if chunk:
                spoken.append(chunk)
                emit(chunk)
    except ValueError:
        raise
    except Exception:
        if not spoken:
            raise
    if action is None:  # stream ended inside the header line
        m = _HEADER.match(header_buf)
        if not m or m.group(1).lower() not in allowed:
            raise ValueError(f"Bad ACTION header: {header_buf[:80]!r}")
        action, question_id = m.group(1).lower(), m.group(2)
    return InterviewerAction(action=action, spoken_text="".join(spoken).strip(), question_id=question_id, reason="")


async def text_chunks(stream) -> AsyncIterator[str]:
    """LiteLLM streaming response -> text deltas."""
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
