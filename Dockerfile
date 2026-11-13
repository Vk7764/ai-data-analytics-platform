# Dockerfile: FastAPI backend, Render Free / Hugging Face Spaces friendly.
FROM python:3.11-slim

ARG INSTALL_DOCKER_CLI=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

RUN if [ "$INSTALL_DOCKER_CLI" = "1" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
      && install -m 0755 -d /etc/apt/keyrings \
      && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
      && chmod a+r /etc/apt/keyrings/docker.asc \
      && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list \
      && apt-get update \
      && apt-get install -y --no-install-recommends docker-ce-cli \
      && apt-get clean && rm -rf /var/lib/apt/lists/*; \
    fi

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ ./backend/

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin app \
    && mkdir -p /app/backend/database /app/backend/logs /app/backend/reports/output /tmp/matplotlib \
    && chown -R app:app /app /tmp/matplotlib

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)"

CMD ["sh", "-c", "exec python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]