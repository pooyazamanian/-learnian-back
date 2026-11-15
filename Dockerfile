# syntax=docker/dockerfile:1
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The package is installed from source, so dependency layers only rebuild when
# the project metadata or the code changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Migrations ship with the image: the `migrate` service runs this same image
# with `alembic upgrade head`, so there is exactly one definition of the app.
COPY alembic.ini ./
COPY alembic ./alembic

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "lurnian.main:app", "--host", "0.0.0.0", "--port", "8000"]
