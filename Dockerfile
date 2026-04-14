# ── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Prevent .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by some Python packages
# (psycopg2-binary, Pillow, lxml, pycairo, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libcairo2-dev \
        libpango1.0-dev \
        libglib2.0-dev \
        libjpeg-dev \
        libpng-dev \
        libxml2-dev \
        libxslt1-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a dedicated prefix so we can copy them
# cleanly into the final image
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Tell Django where to find settings
    DJANGO_SETTINGS_MODULE=FemiCare.settings \
    # Ensure installed packages are on the path
    PYTHONPATH=/install/lib/python3.11/site-packages

WORKDIR /app

# Runtime-only system libraries (no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libglib2.0-0 \
        libjpeg62-turbo \
        libpng16-16 \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy project source
COPY . .

# Collect static files at build time.
# DATABASE_URL must be supplied as a build arg (or set to a dummy value here
# so collectstatic can import settings without a live DB connection).
# Migrations are intentionally left for runtime so they run against the real DB.
ARG DATABASE_URL="postgres://placeholder:placeholder@localhost/placeholder"
ARG ENVIRONMENT="production"
ARG SECRET_KEY="build-time-secret-key-not-used-in-production"

RUN DATABASE_URL=${DATABASE_URL} \
    ENVIRONMENT=${ENVIRONMENT} \
    SECRET_KEY=${SECRET_KEY} \
    python manage.py collectstatic --noinput

EXPOSE 8080

# Run migrations then start Daphne ASGI server
CMD ["sh", "-c", "python manage.py migrate --noinput && daphne -b 0.0.0.0 -p 8080 FemiCare.asgi:application"]
