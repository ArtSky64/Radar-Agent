# ==============================================================================
# Стадия 1: Сборка веб-интерфейса React (Vite + TypeScript + Tailwind CSS)
# ==============================================================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/web

# Установка зависимостей с кэшированием слоев
COPY web/package*.json ./
RUN npm ci

# Сборка фронтенда в web/dist
COPY web/ ./
RUN npm run build

# ==============================================================================
# Стадия 2: Python бэкенд (FastAPI + SQLite + FastEmbed + RAG)
# ==============================================================================
FROM python:3.11-slim AS runner
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DB_NAME=/app/data/app_database.db \
    LOG_FILE=/app/data/app.log \
    ERROR_LOG_FILE=/app/data/errors.log

# Установка необходимых системных утилит и зависимостей для Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Установка Python-библиотек
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    playwright install --with-deps chromium

# Копирование серверного кода приложения
COPY . .

# Копирование готовой сборки React из стадии сборки
COPY --from=frontend-builder /app/web/dist /app/web/dist

# Подготовка рабочей директории для базы данных SQLite и логов
RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/docs || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
