from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401 - registers tables on Base.metadata
from app.db.session import Base, get_db
from app.main import app


@pytest.fixture
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Fresh in-memory SQLite database per test (Postgres-specific types fall back to generic ones)."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def client(db_sessionmaker) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(client):
    """Register + log in a user; returns auth headers."""

    async def _make(email: str = "asha@example.com", password: str = "s3cret-pass") -> dict[str, str]:
        await client.post("/auth/register", json={"email": email, "password": password})
        resp = await client.post("/auth/jwt/login", data={"username": email, "password": password})
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _make
