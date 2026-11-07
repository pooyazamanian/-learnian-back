# Lurnian Backend

Lurnian Language Learning Platform Backend.

## Requirements
- Python >= 3.14, < 3.15
- [uv](https://docs.astral.sh/uv/) for environment and package management

## Setup & Installation

```bash
# Clone the repository and navigate into the project directory
cd lurnian-backend

# Install dependencies and create virtual environment
uv sync
```

## Running the Application

```bash
# Run local development server
uv run uvicorn lurnian.main:app --reload --host 127.0.0.1 --port 8000
```

## Running Tests & Quality Checks

```bash
# Run test suite
uv run pytest

# Run linter and formatter
uv run ruff check .
uv run ruff format --check .
```
