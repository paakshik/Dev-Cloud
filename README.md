# CollabRun Backend
CollabRun is a project-discovery and collaboration API for developers, designers, and teams looking for collaborators.
This FastAPI service stores users, projects, messages, feedback, and avatar bytes in PostgreSQL, with optional Redis caching.

![API screenshot placeholder](./API_SCREENSHOT_PLACEHOLDER.png)

> **Screenshot:** Replace `API_SCREENSHOT_PLACEHOLDER.png` with a real API or database screenshot. No screenshot asset is currently included.

## Features
- REST endpoints for users, projects, messages, feedback, collaboration summaries, login, and statistics.
- SQLAlchemy ORM with PostgreSQL tables in the isolated `collabrun_app` schema.
- Bounded SQLAlchemy connection pool and short pool timeout.
- Connection establishment retries and HTTP `503` on repeated connection/pool failure; write transactions are not automatically replayed.
- Optional Redis cache for list reads and statistics. The service remains usable without Redis.
- Bounded `limit`/`offset` pagination on users, projects, messages, and feedback.
- Password hashing and password exclusion from API response models.
- PostgreSQL timestamps with time zone and database foreign keys, indexes, and additive validation constraints.
- One-time import of bundled sample users, projects, and messages when absent.

## Tech Stack
- Python / FastAPI / Uvicorn.
- SQLAlchemy 2.x and psycopg 3.
- PostgreSQL; local/dev or hosted PostgreSQL is supported.
- Optional Redis (`redis-py`); Redis service provisioning and URL are environment-specific.
- Pydantic request and response validation.

## Getting Started

### Prerequisites
- Python **[TODO: select and verify the supported Python minor version; code and dependencies are tested in the maintainer environment but no version is pinned here].**
- PostgreSQL reachable by the service. Create a dedicated application role with only required privileges; do not use a superuser.
- Redis is optional. Use a Redis-compatible service URL if caching is desired.

### Install
From the repository root, in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` and set the connection values. Do not commit `.env` or credentials.

### Environment variables
| Variable | Required | Example / default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | Yes | `postgresql://app_user:[REDACTED]@host:5432/collabrun` | PostgreSQL connection URL. Legacy `postgres://` is normalized. |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis URL. Omit or leave blank to disable caching. |
| `CACHE_TTL_SECONDS` | No | `30` | Cache expiry for read results. |
| `DB_POOL_SIZE` | No | `5` | Maximum persistent pooled connections per worker. |
| `DB_MAX_OVERFLOW` | No | `5` | Temporary connections above pool size. |
| `DB_POOL_TIMEOUT` | No | `3` | Seconds to wait for a pool connection before returning 503. |
| `DB_CONNECT_TIMEOUT` | No | `5` | PostgreSQL connection timeout in seconds. |
| `SESSION_SECRET` | Recommended | `replace-with-random-secret` | Signs session cookies. Set a long random secret in production. |
| `COOKIE_HTTPS_ONLY` | No | `false` locally, `true` behind HTTPS | Enables secure-only session cookies. |
| `PUBLIC_API_URL` | No | `http://127.0.0.1:8000` | Public backend origin used in generated avatar/OAuth URLs. |
| `FRONTEND_URL` | No | `http://localhost:3000` | Frontend origin for OAuth callbacks. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | No | `[TODO: configure in provider console]` | Optional Google OAuth credentials. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | No | `[TODO: configure in provider console]` | Optional GitHub OAuth credentials. |

### PostgreSQL setup and schema changes
1. Create a PostgreSQL database and a least-privilege role for CollabRun. **[TODO: run a preflight duplicate-name audit before the unique username index is first applied].** Keep the database network-restricted to application hosts.
2. Set `DATABASE_URL` to that role’s connection URL. For local development with a hosted database, use the provider’s externally reachable URL; from a colocated application service, use private networking when available. Never copy a privileged credential into this repository.
3. Start the API. Startup creates/uses schema `collabrun_app`, creates missing tables, applies additive indexes/constraints, and imports sample records only if their IDs are absent.

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The backend currently uses SQLAlchemy `create_all` plus additive PostgreSQL DDL, **not a versioned migration tool**. Before shipping schema changes, review the generated DDL and plan a migration system (for example Alembic): **[TODO: establish migration workflow and verify constraint validation on production data].** Do not manually drop or recreate the Render database.

### Redis setup
For local Redis, start a Redis service separately and set `REDIS_URL=redis://localhost:6379/0`. For deployment, configure `REDIS_URL` from the Redis provider’s private connection URL. Cache hits are best-effort only; list results and summary counts use short TTLs and writes invalidate related keys. Cache failures are logged and treated as cache misses; PostgreSQL remains the source of truth. Cache invalidation is best-effort and uses `SCAN`, not `KEYS`.

## Usage
Start the service with Uvicorn as shown above. Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

`/health` returns API status and whether Redis is connected or disabled/unavailable. It does not replace monitoring of PostgreSQL itself.

## API Documentation
When running locally:
- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI schema: <http://127.0.0.1:8000/openapi.json>

Selected endpoints:
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/users?limit=100&offset=0` | List users, paginated |
| `POST` | `/api/v1/users` | Create user |
| `GET` | `/api/v1/projects?limit=100&offset=0` | List projects, paginated |
| `POST` | `/api/v1/projects` | Create project |
| `GET` | `/api/v1/messages?user_id=...&limit=100&offset=0` | List a user’s messages |
| `POST` | `/api/v1/messages` | Create message/application |
| `GET` | `/api/v1/feedbacks/{user_id}?limit=100&offset=0` | List profile feedback |
| `GET` | `/api/v1/stats` | Aggregate project/user/message counts |
| `GET` | `/health` | API and Redis status |

List endpoints cap `limit` at 100. Deep-page cursor pagination is a possible future improvement if result volumes require it.

## Design Decisions
- **Schema isolation:** all application tables live in `collabrun_app`, avoiding collisions with unrelated tables in a shared PostgreSQL database.
- **Normalized core entities:** users, projects, messages, and feedback have separate tables; references use foreign keys. Profile skills and linked accounts remain JSON for now because the current application treats them as profile attributes and does not query them relationally. **[TODO: normalize skill catalog/endorsements if skill-level queries become a core feature].**
- **Timestamps:** database columns use `TIMESTAMP WITH TIME ZONE`; API values serialize as ISO timestamps. Historical timestamps are retained as stored.
- **Caching:** Redis is an optional cache-aside layer for list reads and statistics. PostgreSQL remains authoritative; TTL and best-effort invalidation limit stale results.
- **Connection capacity:** defaults allow at most 10 app connections per worker (pool 5 plus overflow 5). Recalculate pool and worker counts against the database’s connection limit before scaling workers.
- **Query behavior:** list reads are bounded and ordered with indexes for common filters/orderings. Validate production plans with `EXPLAIN (ANALYZE, BUFFERS)` using representative data before tuning.
- **Migration safety:** startup DDL creates missing tables and adds indexes plus `CHECK ... NOT VALID` constraints; it does not drop tables or rewrite existing rows. Existing schemas are preserved. Versioned migrations are not yet configured. Backups and restore drills must be configured in Render/database operations; this application cannot enable provider-level snapshots or point-in-time recovery itself.
- **Security boundary:** use a dedicated database role, TLS/private networking, strong `SESSION_SECRET`, HTTPS-only cookies in production, and provider-managed backups. Sensitive OAuth credentials belong in secret environment settings, never this file.

## Testing
Backend tests use an isolated in-memory SQLite database with schema translation; they do not connect to or mutate Render PostgreSQL.

```powershell
cd backend
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Current suite covers API signup/login and response secrecy, project creation/validation and stats, message/status flow, feedback CRUD, avatar upload/readback, pagination, cache use/invalidation, Redis JSON round trips, pattern invalidation, and fail-open behavior. It uses isolated SQLite and mocked Redis; PostgreSQL DDL and a live Redis connection still require deployment integration checks. **[TODO: add pool exhaustion/503 tests, PostgreSQL constraint migration tests, and coverage reporting].**

## Deployment
Hosting provider and public API URL: **[TODO: confirm deployment target and URL].** Service build/start commands and health-check settings: **[TODO: fill in from the deployed service configuration].** Set secrets in the hosting provider’s secret environment variables rather than committing credentials. Configure managed PostgreSQL backups/PITR and test restoration outside the app deployment workflow.

## Troubleshooting
- **`DATABASE_URL is missing`:** copy `backend/.env.example` to `.env` and set a reachable PostgreSQL URL.
- **Pool timeout / HTTP 503:** check database reachability and connection usage; lower worker count or tune bounded pool settings to fit database limits.
- **Redis unavailable:** API should continue with uncached DB reads; check `REDIS_URL` and `/health` if cache is expected.
- **Existing database schema conflict:** confirm the app has permission to create/use `collabrun_app`; do not change unrelated `public` tables.
- **Constraint migration warning:** inspect historical rows and logs. Existing data is not automatically rewritten or deleted.
- **Avatar disappears after deployment:** avatar bytes are stored in PostgreSQL; check row persistence and `GET /api/v1/users/{id}/avatar`.
- **OAuth redirect mismatch:** align provider callback URLs with `PUBLIC_API_URL` and configure frontend origin with `FRONTEND_URL`.

## License
**License: [TODO: choose and add a license before distribution].**
