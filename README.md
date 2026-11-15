# Lurnian Backend

Lurnian Language Learning Platform Backend.

## Requirements
- Python >= 3.14, < 3.15

## Setup & Installation

```bash
# Clone the repository and navigate into the project directory
cd lurnian-backend

# Create a virtual environment (once)
python -m venv .venv

# Activate it
source .venv/Scripts/activate   # Windows (Git Bash)
# source .venv/bin/activate     # Linux / macOS
# .venv\Scripts\activate        # Windows (PowerShell)

# Install the package with development dependencies
pip install -e ".[dev]"
```

> If you named the environment differently (for example `env`), only the
> activation path changes; `.venv/` and `env/` are both git-ignored.

## Running the Application

```bash
uvicorn lurnian.main:app --reload --host 127.0.0.1 --port 8000
```

## Database

- **PostgreSQL 18** (latest minor of the major is kept up to date)
- **SQLAlchemy 2.1** in async mode
- **psycopg 3** as the PostgreSQL driver
- **Alembic** for schema migrations

Everything the service needs to run locally is in `docker-compose.yml`.

| Service | Image | Host address | Purpose |
| --- | --- | --- | --- |
| `db` | `postgres:18-alpine` | `127.0.0.1:5432` | primary database |
| `redis` | `redis:8-alpine` | `127.0.0.1:6379` | rate limiting, caching and queues |
| `seaweedfs` | `chrislusf/seaweedfs` | `127.0.0.1:8333` | S3 API for `*_object_key` assets |
| `mailpit` | `axllent/mailpit` | SMTP `2525`, UI `8026` | catches outgoing mail |
| `migrate` | built image | one-shot | `alembic upgrade head` |
| `api` | built image | `127.0.0.1:8000` | the application |

The `api` container starts only after the database is healthy and migrations
have completed; `restart: unless-stopped` only affects it, never the one-shot
migration container.

```bash
# Build and start everything (migrations run automatically)
docker compose up -d --build

# Follow the application log
docker compose logs -f api

# Stop (volumes and data are kept)
docker compose down

# Stop and delete all local data
docker compose down -v
```

API: http://127.0.0.1:8000 · docs: http://127.0.0.1:8000/docs · mail UI: http://127.0.0.1:8026

### PostgreSQL 18 volume layout

PostgreSQL 18 images keep the cluster in a major-version subdirectory, so the
volume is mounted at `/var/lib/postgresql` (not `/var/lib/postgresql/data`).
The compose file uses the volume `pgdata18` for exactly that reason. A volume
created by the previous layout (`lurnian-backend_lurnian_pgdata`) is ignored;
remove it once you are sure it holds nothing you need:

```bash
docker volume rm lurnian-backend_lurnian_pgdata
```

Running the application outside Docker (`.venv`) uses `DATABASE_URL` from
`.env`, which points at the same `127.0.0.1:5432`.

`GET /health` is a liveness probe with no database dependency; `GET /ready` reports readiness including database connectivity and returns 503 while the database is unavailable.

See [docs/decisions/0001-database-postgresql.md](docs/decisions/0001-database-postgresql.md) for the full rationale and architecture decisions.

## Running Tests & Quality Checks

```bash
# Run test suite
pytest

# Run linter and formatter
ruff check .
ruff format --check .
```
