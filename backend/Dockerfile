FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# gnupg: o worker decifra os backups (em streaming, sem gravar em disco) para
# a verificação profunda; o backend lê a chave pública.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gnupg \
 && rm -rf /var/lib/apt/lists/*

# INSTALL_DEV=true inclui pytest/httpx/ruff (para rodar a suíte no container).
ARG INSTALL_DEV=false

COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip \
 && if [ "$INSTALL_DEV" = "true" ]; then pip install ".[dev]"; else pip install .; fi

COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests
COPY worker-entrypoint.sh /usr/local/bin/worker-entrypoint.sh

# uid 10001 = o mesmo do usuário "backup" do container sshd: os arquivos que
# chegam por rsync ficam com esse dono e o worker consegue movê-los/apagá-los.
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser
ENV HOME=/home/appuser

EXPOSE 8000

# Aplica migrações, roda o seed idempotente e sobe a API. O worker usa a mesma
# imagem com outro command (python -m app.worker).
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 -w ${WEB_CONCURRENCY:-3} --timeout 600 --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-*}\" --access-logfile - --error-logfile -"]
