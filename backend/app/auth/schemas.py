import uuid
from datetime import datetime

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    name: str | None = None
    created_at: datetime


class UserCreate(schemas.BaseUserCreate):
    name: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    name: str | None = None
