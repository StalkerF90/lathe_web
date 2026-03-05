# ─────────────────────────────────────────────
#  Dockerfile — Система контроля токарных станков
# ─────────────────────────────────────────────
FROM python:3.11-slim

# Метаданные
LABEL maintainer="lathe-control"
LABEL description="Streamlit app for lathe machine monitoring"

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Зависимости Python (кешируются отдельным слоем)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Исходный код
COPY app.py           .
COPY manage_users.py  .
COPY generate_config.py .

# Создаём директорию для данных (переопределяется volume)
RUN mkdir -p /data

# Переменные окружения
ENV DB_PATH=/data/app.db
ENV CONFIG_PATH=/data/config.yml
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV STREAMLIT_SERVER_ENABLE_CORS=false
ENV STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=true
ENV PYTHONUNBUFFERED=1

# Точка входа: генерируем config если не существует, затем запускаем
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
