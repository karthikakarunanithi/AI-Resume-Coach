import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth.users import current_active_user
from app.config import get_settings
from app.db.models import JobDescription, Resume, User
from app.db.session import get_db
from app.llm.client import LLMClient
from app.llm.deps import get_llm
from app.llm.errors import user_message
from app.llm.schemas import CandidateProfile, JDAnalysis
from app.services.parsers import analyze_jd, parse_resume
from app.services.text_extract import UnsupportedFileError, detect_file_type, extract_text

logger = logging.getLogger("coach.api")
router = APIRouter()

DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_active_user)]
LLM = Annotated[LLMClient, Depends(get_llm)]

MIN_RESUME_CHARS = 100


class ResumeRead(BaseModel):
    id: uuid.UUID
    parsed_profile: CandidateProfile
    created_at: datetime


class JDCreate(BaseModel):
    raw_text: str = Field(min_length=50, max_length=20_000)


class JDRead(BaseModel):
    id: uuid.UUID
    analysis: JDAnalysis
    created_at: datetime


def _resume_read(r: Resume) -> ResumeRead:
    return ResumeRead(id=r.id, parsed_profile=CandidateProfile.model_validate(r.parsed_profile), created_at=r.created_at)


def _jd_read(jd: JobDescription) -> JDRead:
    return JDRead(id=jd.id, analysis=JDAnalysis.model_validate(jd.skills), created_at=jd.created_at)


def _llm_failed(task: str, exc: Exception) -> HTTPException:
    logger.exception("%s failed", task)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, user_message(exc, task))


@router.post("/resumes", status_code=status.HTTP_201_CREATED, response_model=ResumeRead, tags=["resumes"])
async def upload_resume(file: UploadFile, user: CurrentUser, db: DB, llm: LLM) -> ResumeRead:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {get_settings().max_upload_mb} MB")
    try:
        text = await run_in_threadpool(extract_text, data)
    except UnsupportedFileError as e:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e)) from e
    if len(text) < MIN_RESUME_CHARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No readable text found. Scanned/image-only PDFs are not supported yet.",
        )

    try:
        profile = await parse_resume(llm, text)
    except Exception as e:  # provider errors and invalid JSON both map to 502
        raise _llm_failed("Resume parsing", e) from e

    # Store the original only after parsing succeeds, so failures leave no orphan files
    resume_id = uuid.uuid4()
    path = get_settings().upload_dir / str(user.id) / f"{resume_id}.{detect_file_type(data)}"
    path.parent.mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(path.write_bytes, data)

    resume = Resume(id=resume_id, user_id=user.id, file_url=path.as_uri(), parsed_profile=profile.model_dump())
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return _resume_read(resume)


@router.get("/resumes", response_model=list[ResumeRead], tags=["resumes"])
async def list_resumes(user: CurrentUser, db: DB) -> list[ResumeRead]:
    rows = await db.scalars(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())
    )
    return [_resume_read(r) for r in rows]


@router.post(
    "/job-descriptions", status_code=status.HTTP_201_CREATED, response_model=JDRead, tags=["job-descriptions"]
)
async def create_job_description(body: JDCreate, user: CurrentUser, db: DB, llm: LLM) -> JDRead:
    try:
        analysis = await analyze_jd(llm, body.raw_text)
    except Exception as e:  # provider errors and invalid JSON both map to 502
        raise _llm_failed("Job description analysis", e) from e

    jd = JobDescription(user_id=user.id, raw_text=body.raw_text, skills=analysis.model_dump())
    db.add(jd)
    await db.commit()
    await db.refresh(jd)
    return _jd_read(jd)


@router.get("/job-descriptions", response_model=list[JDRead], tags=["job-descriptions"])
async def list_job_descriptions(user: CurrentUser, db: DB) -> list[JDRead]:
    rows = await db.scalars(
        select(JobDescription)
        .where(JobDescription.user_id == user.id)
        .order_by(JobDescription.created_at.desc())
    )
    return [_jd_read(jd) for jd in rows]
