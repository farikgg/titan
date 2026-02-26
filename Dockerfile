FROM python:3.12-slim

# Системные зависимости (tesseract для OCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости отдельно (кэш Docker слоя)
COPY pyproject.toml uv.lock ./

# Устанавливаем uv и зависимости
RUN pip install --no-cache-dir uv && \
    uv sync --frozen --no-dev

# Копируем исходники
COPY . .

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV TESSERACT_CMD=/usr/bin/tesseract

EXPOSE 8000

# Запуск FastAPI
CMD ["uv", "run", "uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
