# Transcript Intelligence web UI.   Build:  docker build -t ti-web:local .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    TI_HOST=0.0.0.0

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Only the application code goes in. Secrets (.env), data/, tests and local venvs are excluded by .dockerignore;
# the graph lives in Neo4j, so the container does not need the raw transcripts.
COPY src ./src

# Run as a non-root user.
RUN useradd --system --uid 10001 --no-create-home app
USER 10001
WORKDIR /app/src

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'), timeout=4)"

CMD ["python", "-m", "ti.web"]
