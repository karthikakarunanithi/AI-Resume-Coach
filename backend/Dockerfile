FROM python:3.11-slim
WORKDIR /srv/backend
COPY backend/pyproject.toml .
COPY backend/app ./app
COPY backend/alembic.ini .
COPY backend/migrations ./migrations
RUN pip install --no-cache-dir .
COPY config /srv/config
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
