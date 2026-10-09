
    # Packages the Python application using a multi-stage build.
    # Prepares dependencies separately from the final runtime image.
    # Runs the application as a non-root user and includes a health check.

    FROM python:3.12-slim AS builder
    WORKDIR /build
    COPY requirements.txt .
    RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

    FROM python:3.12-slim AS runtime
    ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
    WORKDIR /app
    COPY --from=builder /wheels /wheels
    COPY requirements.txt .
    RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
        && rm -rf /wheels \
        && useradd --create-home --uid 10001 appuser
    COPY --chown=appuser:appuser . /app
    RUN chmod 644 /app/app.py
    USER appuser
    EXPOSE 8080
    HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
        CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=2)" || exit 1
    CMD ["python", "app.py"]
