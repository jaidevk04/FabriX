# Fabrix: one container, one port. `docker compose up -d --build` and open http://<host>:8000
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COGNITION_HOST=0.0.0.0 \
    COGNITION_PORT=8000 \
    COGNITION_DB=/data/platform.db \
    COGNITION_CORE_AGENTS=false \
    FORWARDED_ALLOW_IPS=*

WORKDIR /app

# Pinned dependency lock first, so code changes do not reinstall it.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
# Host file modes can be restrictive (for example rw-rw----); the runtime user must be able to read the code.
RUN chmod -R a+rX /app && pip install --no-deps -e .

# Run as a normal user; the SQLite database lives on the /data volume.
RUN useradd --system --create-home --uid 10001 fabrix \
    && mkdir -p /data \
    && chown fabrix:fabrix /data
USER fabrix
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/health' % os.environ.get('COGNITION_PORT','8000'), timeout=4)"

CMD ["cognition", "serve"]
