import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str) -> str:
    """Load a versioned prompt, e.g. load_prompt("resume_parser_v1")."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def render_prompt(name: str, **values: object) -> str:
    """Fill {placeholders} by name. Unlike str.format, literal JSON braces in the prompt are left alone."""
    template = load_prompt(name)
    missing = set(re.findall(r"\{(\w+)\}", template)) - values.keys()
    if missing:
        raise KeyError(f"{name}: missing values for {sorted(missing)}")
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]), template)
