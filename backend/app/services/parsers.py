from app.llm.client import LLMClient
from app.llm.schemas import CandidateProfile, JDAnalysis
from app.prompts import load_prompt
from app.services.pii import redact_pii

RESUME_PROMPT = "resume_parser_v1"
JD_PROMPT = "jd_analyzer_v1"
MAX_INPUT_CHARS = 20_000  # ~5k tokens; real resumes and JDs are far shorter


async def parse_resume(llm: LLMClient, resume_text: str) -> CandidateProfile:
    messages = [
        {"role": "system", "content": load_prompt(RESUME_PROMPT)},
        {"role": "user", "content": f"RESUME:\n{redact_pii(resume_text)[:MAX_INPUT_CHARS]}"},
    ]
    return await llm.structured("resume_parser", messages, CandidateProfile, prompt_version=RESUME_PROMPT)


async def analyze_jd(llm: LLMClient, jd_text: str) -> JDAnalysis:
    messages = [
        {"role": "system", "content": load_prompt(JD_PROMPT)},
        {"role": "user", "content": f"JOB DESCRIPTION:\n{redact_pii(jd_text)[:MAX_INPUT_CHARS]}"},
    ]
    return await llm.structured("jd_analyzer", messages, JDAnalysis, prompt_version=JD_PROMPT)
