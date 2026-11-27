FROM python:3.12-slim

# Метаданные сборки (передаёт CI; пустые — нормальный случай при локальной сборке).
ARG APP_VERSION=
ARG GIT_COMMIT=
ARG BUILD_TIME=

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

USER nobody
ENV CONFIG_PATH=/app/config/config.yaml

LABEL org.opencontainers.image.title="frigate-to-tg" \
      org.opencontainers.image.description="Frigate alerts to Telegram topics via HTTP API" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIME}"

CMD ["python", "-m", "app"]
