"""Turn LLM provider failures into messages people can act on.

Account and configuration problems (no credit, bad key, unknown model, rejected parameter) can't be fixed by
retrying, so saying "please try again" hides the cause; transient ones (timeouts, rate limits, 5xx) can.
"""

import re

import litellm

_PROVIDER_MESSAGE = re.compile(r'"message"\s*:\s*"([^"]+)"')


def describe(exc: BaseException, limit: int = 300) -> str:
    """Short one-line description for logs and the llm_calls table."""
    text = str(exc).replace("\n", " ")
    m = _PROVIDER_MESSAGE.search(text)
    detail = m.group(1) if m else text
    return f"{type(exc).__name__}: {detail}"[:limit]


def user_message(exc: BaseException, what: str) -> str:
    text = str(exc).lower()
    if "credit balance" in text or "billing" in text or "quota" in text:
        return f"{what} failed: the AI provider account has no credit left. Add credit, then try again."
    if isinstance(exc, litellm.AuthenticationError) or "api key" in text or "x-api-key" in text:
        return f"{what} failed: the AI provider rejected the API key. Check the keys in .env."
    if isinstance(exc, litellm.NotFoundError) or "model_not_found" in text or "does not exist" in text:
        return f"{what} failed: a model in config/models.yaml isn't available. Check the model names."
    if isinstance(exc, litellm.UnsupportedParamsError | litellm.BadRequestError):
        return f"{what} failed: the AI provider rejected the request ({describe(exc, 200)})."
    return f"{what} failed, please try again."
