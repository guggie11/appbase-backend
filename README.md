# appbase-backend

[![CI Backend](https://github.com/guggie11/appbase-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/guggie11/appbase-backend/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)

The FastAPI backend for [Appbase](https://github.com/guggie11/appbase-infrastructure) — a production-ready boilerplate for internal admin applications.

Provides a fully async REST API with JWT authentication, RBAC, dynamic menus, audit logging, and notifications, backed by PostgreSQL and Redis.

---

## Stack

| Layer | Technology |
|-------|------------|
| Framework | FastAPI 0.115 (async) |
| ORM | SQLAlchemy 2 (async) |
| Database | PostgreSQL 16 |
| Cache / Token BL | Redis 7 |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Auth | python-jose (JWT) + pwdlib (Argon2) |
| Rate limiting | SlowAPI |
| Email | aiosmtplib |
| Package manager | uv |
| Linting / Typing | Ruff + Pyright |
| Testing | pytest + pytest-asyncio |

---

## Quick Start (backend only)

**Prerequisites:** Python 3.11+, PostgreSQL 16, Redis 7, uv

```bash
git clone https://github.com/guggie11/appbase-backend.git
cd appbase-backend

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL, REDIS_URL, SECRET_KEY, SMTP_HOST

# Run migrations
uv run alembic upgrade head

# Start development server (auto-reload)
uv run fastapi dev src/app/main.py
```

API available at **http://localhost:8000**  
Interactive docs at **http://localhost:8000/docs**

---

## API Endpoints

### Auth — `/api/v1/auth`

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/login` | Login, returns access + refresh tokens |
| `POST` | `/auth/refresh` | Refresh access token |
| `POST` | `/auth/logout` | Logout (blacklist token) |
| `POST` | `/auth/register` | Self-registration |
| `POST` | `/auth/verify-email` | Verify email with token |
| `POST` | `/auth/forgot-password` | Send password reset email |
| `POST` | `/auth/reset-password` | Reset password with token |

### Users — `/api/v1/users`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/users` | List users (paginated) |
| `POST` | `/users` | Create user |
| `GET` | `/users/{id}` | Get user by ID |
| `PUT` | `/users/{id}` | Update user |
| `DELETE` | `/users/{id}` | Soft delete user |
| `POST` | `/users/invite` | Send invitation email |
| `POST` | `/users/accept-invitation` | Accept invite, set password |

### Roles & Permissions — `/api/v1/roles`, `/api/v1/permissions`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/roles` | List roles |
| `POST` | `/roles` | Create role |
| `PUT` | `/roles/{id}` | Update role |
| `DELETE` | `/roles/{id}` | Delete role |
| `GET` | `/permissions` | List all permissions |
| `POST` | `/roles/{id}/permissions` | Assign permissions to role |

### Menus — `/api/v1/menus`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/menus` | List all menus (admin) |
| `GET` | `/menus/my-menus` | Get menus visible to current user |
| `POST` | `/menus` | Create menu item |
| `PUT` | `/menus/{id}` | Update menu item |
| `DELETE` | `/menus/{id}` | Delete menu item |

### Notifications — `/api/v1/notifications`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/notifications` | List notifications for current user |
| `POST` | `/notifications/{id}/read` | Mark notification as read |
| `POST` | `/notifications/read-all` | Mark all as read |

### Audit Logs — `/api/v1/audit-logs`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/audit-logs` | Query audit logs (filterable, paginated) |

### Dashboard — `/api/v1/dashboard`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dashboard` | Summary stats (users, roles, activity) |

### Profile — `/api/v1/profile`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/profile` | Get current user profile |
| `PUT` | `/profile` | Update profile (name, avatar) |
| `PUT` | `/profile/password` | Change password |

### Settings — `/api/v1/settings`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/settings` | Get application settings |
| `PUT` | `/settings` | Update settings (super admin only) |

---

## Project Structure

```
appbase-backend/
├── src/
│   └── app/
│       ├── main.py              # FastAPI app factory, middleware setup
│       ├── api/
│       │   └── v1/
│       │       ├── router.py    # Aggregates all v1 routes
│       │       ├── auth/        # Login, logout, register, reset
│       │       ├── users/       # User CRUD + invite
│       │       ├── roles/       # Role management
│       │       ├── permissions/ # Permission listing + assignment
│       │       ├── menus/       # Dynamic menu CRUD
│       │       ├── notifications/
│       │       ├── audit_logs/
│       │       ├── dashboard/
│       │       ├── profile/
│       │       ├── settings/
│       │       └── deps.py      # Shared FastAPI dependencies (get_db, current_user, rbac)
│       ├── core/
│       │   ├── config.py        # Pydantic Settings (reads .env)
│       │   ├── database.py      # Async SQLAlchemy engine + session factory
│       │   └── security.py      # JWT creation/validation, password hashing
│       ├── models/              # SQLAlchemy ORM models
│       │   ├── user.py
│       │   ├── rbac.py          # Role, Permission, RolePermission, UserRole
│       │   ├── menu.py
│       │   ├── audit.py
│       │   ├── notification.py
│       │   └── token.py         # Blacklisted token store
│       ├── schemas/             # Pydantic request/response models
│       ├── middleware/
│       │   └── audit.py         # Middleware that auto-logs mutating requests
│       └── utils/
│           └── email.py         # aiosmtplib email sender
├── alembic/
│   ├── env.py
│   └── versions/               # Migration scripts
├── tests/
│   ├── conftest.py              # Async test client, in-memory DB fixtures
│   ├── test_auth.py
│   ├── test_permissions.py
│   └── test_main.py
├── scripts/
│   └── create_superadmin.py
├── pyproject.toml
└── alembic.ini
```

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `APP_NAME` | `Appbase` | No | Application display name |
| `DEBUG` | `False` | No | Debug mode — never `True` in production |
| `DATABASE_URL` | `postgresql+psycopg://appbase:appbase@localhost:5432/appbase` | **Yes** | Async PostgreSQL DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | **Yes** | Redis connection string |
| `SECRET_KEY` | — | **Yes** | JWT signing secret. Generate: `openssl rand -hex 32` |
| `ALGORITHM` | `HS256` | No | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | No | Access token TTL (minutes) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | No | Refresh token TTL (days) |
| `CORS_ORIGINS` | `http://localhost:5173` | No | Comma-separated allowed origins |
| `SMTP_HOST` | `localhost` | No | SMTP host (use `localhost` + Mailpit for dev) |
| `SMTP_PORT` | `1025` | No | SMTP port |
| `FRONTEND_URL` | `http://localhost:5173` | No | Used in email links (password reset, invite) |

---

## Testing

The test suite uses an in-memory SQLite database and `fakeredis` — no running services required.

```bash
# Run all tests
uv run pytest tests/ -v

# Run a specific file
uv run pytest tests/test_auth.py -v

# Run with coverage
uv run pytest tests/ --cov=src/app --cov-report=term-missing
```

Test fixtures in `conftest.py` provide:
- An async test client (`AsyncClient`)
- An in-memory SQLite async engine
- Isolated DB state per test

---

## Database Migration Guide

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Generate a migration from model changes
uv run alembic revision --autogenerate -m "describe_your_change"

# Always review the generated file before applying
# File: alembic/versions/<timestamp>_describe_your_change.py

# Roll back the last migration
uv run alembic downgrade -1

# Downgrade to a specific revision
uv run alembic downgrade <revision_id>

# View current revision
uv run alembic current

# View full history
uv run alembic history --verbose
```

> **Important:** Never edit a migration file after it has been applied to any shared database. Create a new migration instead.

---

## Code Quality

```bash
# Lint and auto-fix
uv run ruff check src/ --fix
uv run ruff format src/

# Type checking
uv run pyright src/
```

---

## License

MIT © 2024 [guggie11](https://github.com/guggie11)
