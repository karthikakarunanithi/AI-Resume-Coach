import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin\.com|github\.com)/\S+", re.IGNORECASE)
# Candidate phone-like runs; filtered by digit count so date ranges like "2019-2023" survive
PHONE_RE = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")


def _redact_phone(match: re.Match[str]) -> str:
    digits = sum(c.isdigit() for c in match.group())
    return "[PHONE]" if 10 <= digits <= 13 else match.group()


def redact_pii(text: str) -> str:
    """Remove contact details before text is sent to an LLM (plan rule 5.3.10)."""
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = URL_RE.sub("[URL]", text)
    return PHONE_RE.sub(_redact_phone, text)
