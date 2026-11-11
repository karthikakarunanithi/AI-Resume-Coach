"""Run the real resume parser / JD analyzer on a local file and print the JSON.

Usage (from backend/, with API keys in ../.env):
    python -m scripts.parse_file resume path/to/resume.pdf
    python -m scripts.parse_file jd path/to/job_description.txt
"""

import asyncio
import sys
from pathlib import Path

from app.llm.client import LLMClient
from app.services.parsers import analyze_jd, parse_resume
from app.services.text_extract import extract_text


async def main(kind: str, path: Path) -> None:
    llm = LLMClient()
    if kind == "resume":
        result = await parse_resume(llm, extract_text(path.read_bytes()))
    else:
        result = await analyze_jd(llm, path.read_text(encoding="utf-8"))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in {"resume", "jd"}:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
