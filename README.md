[![CI](https://github.com/guggie11/appbase-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/guggie11/appbase-backend/actions/workflows/ci.yml)

# Appbase Backend

FastAPI backend skeleton for Appbase project.

## Tech Stack

- **FastAPI** — async web framework
- **SQLAlchemy 2.x** — async ORM
- **PostgreSQL** via psycopg3
- **Redis** via redis-py async
- **Alembic** — database migrations
- **pydantic-settings** — config via env
- **pwdlib[argon2]** — password hashing
- **python-jose** — JWT
- **SlowAPI** — rate limiting
- **uv** — package & env management

## Dev Setup

```bash
# 1. Copy env file
cp .env.example .env
# Edit .env with your local DB/Redis URLs and a real SECRET_KEY

# 2. Install dependencies
uv sync

# 3. Run dev server
uv run fastapi dev src/app/main.py

# 4. Run migrations
uv run alembic upgrade head

# 5. Run tests
uv run pytest
```

## Project Structure

```
src/app/
├── main.py          # FastAPI app, middleware, health check
├── core/
│   ├── config.py    # Settings (pydantic-settings)
│   ├── database.py  # Async SQLAlchemy engine/session
│   ├── redis.py     # Async Redis client
│   └── security.py  # JWT + Argon2 helpers
├── api/
│   ├── deps.py      # Shared dependencies
│   └── v1/router.py # v1 API router
├── models/          # SQLAlchemy models
├── schemas/         # Pydantic schemas
├── middleware/      # Custom middleware
└── utils/           # Utilities
```

## Alembic

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback one step
uv run alembic downgrade -1
```
