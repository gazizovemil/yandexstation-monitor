FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YANDEX_MONITOR_DATA_DIR=/data

RUN pip install --no-cache-dir 'websockets>=13,<17' 'yandex-music>=2.2,<4'
WORKDIR /app
COPY monitor.py /app/monitor.py
CMD ["python", "/app/monitor.py", "loop"]
