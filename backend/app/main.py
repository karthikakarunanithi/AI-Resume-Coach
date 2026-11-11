import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.progress import router as progress_router
from app.api.sessions import router as sessions_router
from app.api.voice import router as voice_router
from app.auth.schemas import UserCreate, UserRead, UserUpdate
from app.auth.users import auth_backend, fastapi_users
from app.config import get_settings
from app.llm.call_log import get_call_logger
from app.observability import setup_observability

logging.basicConfig(level=logging.INFO)
setup_observability()

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_call_logger().flush()  # don't lose queued usage records on shutdown


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(progress_router)  # before the users router, so /users/me/progress isn't read as /users/{id}
app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=["auth"])
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"])
app.include_router(fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"])
app.include_router(documents_router)
app.include_router(sessions_router)
app.include_router(voice_router)
