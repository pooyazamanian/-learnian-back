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

Development and CI run PostgreSQL 18 in containers (Docker Compose locally, a dedicated service container in CI). Connection pooling comes from SQLAlchemy's built-in pool.

```bash
# Start the local PostgreSQL instance
docker compose up -d db

# Apply migrations (after they are generated)
alembic upgrade head
```

Connection settings come from `DATABASE_URL` (see `.env.example`).

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
