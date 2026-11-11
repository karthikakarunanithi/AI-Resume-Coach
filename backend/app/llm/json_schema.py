"""JSON schemas for structured outputs, cleaned to what strict structured outputs accept on every provider.

- Claude requires `additionalProperties: false` on every object and rejects numeric, string-length and
  array-size constraints.
- Strict mode on OpenAI-compatible providers (OpenAI, Groq) also requires every property to be listed in
  `required` and doesn't take `default`.
LiteLLM forwards a Pydantic schema as-is (it only closes the top-level object), so we clean it here. Pydantic
still enforces the constraints and fills defaults when the reply is validated; an optional field is still
optional in Python, the model just has to send it (as null or [] when it has nothing).
"""

from typing import Any

from pydantic import BaseModel

UNSUPPORTED_KEYWORDS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "default",
}


def _clean(node: Any) -> Any:
    if isinstance(node, list):
        return [_clean(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: _clean(v) for k, v in node.items() if k not in UNSUPPORTED_KEYWORDS}
    if out.get("type") == "object" or "properties" in out:
        if isinstance(node.get("additionalProperties"), dict):
            raise ValueError("Open-ended maps (dict[str, X]) can't be used in structured outputs; use a list of items")
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}))
    return out


def structured_output_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _clean(model.model_json_schema())


def response_format_for(model: type[BaseModel]) -> dict[str, Any]:
    """OpenAI-style response_format, which LiteLLM maps to each provider's structured-output feature."""
    return {
        "type": "json_schema",
        "json_schema": {"name": model.__name__, "schema": structured_output_schema(model), "strict": True},
    }
