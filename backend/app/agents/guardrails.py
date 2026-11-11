"""Rule-based input guardrail: cheap, deterministic, runs on every answer before any LLM sees it."""

import re
from dataclasses import dataclass

# Second-person phrasing only: candidates legitimately *describe* prompt injection
# ("an attacker writes 'ignore previous instructions'") in GenAI interviews.
INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override) (all )?(of )?your (previous |prior |earlier )?(instructions|rules|prompt)",
    # needs a scoring word, so "give me five minutes" is fine
    (r"\b(give|award|rate|score|mark) me (a |an )?(10|ten|5|five|full|perfect|maximum|max|top) ?"
    r"(/ ?\d+|out of|marks|points|score|rating|stars)"),
    r"\byou are (now )?(no longer|not) (an |the )?interviewer\b",
    r"\b(reveal|show me|tell me) (the |your )(plan|prompt|rubric|scor\w*|instructions)\b",
    r"\bwhat (is|are) your (system prompt|instructions)\b",
]
ABUSE_PATTERNS = [r"\b(fuck|shit|bitch|bastard|idiot|stupid bot)\b"]

_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)
_ABUSE_RE = re.compile("|".join(ABUSE_PATTERNS), re.IGNORECASE)

REDIRECTS = {
    "injection": "Let's keep this a fair practice interview, so I'll stick to the questions. "
    "Could you answer the question I asked?",
    "abuse": "I understand interviews can be stressful. Let's keep it professional and get back to the question.",
}


@dataclass
class GuardrailResult:
    safe: bool
    reason: str | None = None

    @property
    def redirect(self) -> str:
        return REDIRECTS[self.reason or "injection"]


def check_answer(text: str) -> GuardrailResult:
    if _INJECTION_RE.search(text):
        return GuardrailResult(safe=False, reason="injection")
    if _ABUSE_RE.search(text):
        return GuardrailResult(safe=False, reason="abuse")
    return GuardrailResult(safe=True)
