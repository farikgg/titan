## Стек технологий

1. Backend (Core)
- Language: Python 3.11+.
- Web Framework: FastAPI.
- Database: PostgreSQL.
- ORM: SQLAlchemy 2.0 (обязательно асинхронная версия).
- Migrations: Alembic.
- AI Inference: Groq API.
- Validation: Pydantic v2.

2. Infrastructure & Async Tasks
- Task Queue: Celery + Redis.
- PDF Engine: WeasyPrint + Jinja2.
- Bitrix Client: fast_bitrix24 (библиотека). Если что поищем альтернативы

3. Frontend (TMA) Пока что так, если что подкоррекируем
Framework: React (Vite) или Vue 3.
UI Kit: Telegram UI (или shadcn/ui, если React).
State Management: Zustand (React) / Pinia (Vue).
HTTP Client: Axios / TanStack Query (для кеширования данных на фронте).

## Архитектура проекта V_1.0
```
src/
├── app/
├── api/                   # Роутеры (Endpoints)
│   ├── v1/
│   │   ├── auth.py        # Валидация initData от Telegram
│   │   ├── deals.py       # Получение/обновление сделок
│   │   └── kp_gen.py      # Кнопка "Сформировать КП"
├── core/                  # Конфиги, Env, Exception Handlers
├── db/                    # База данных
│   ├── models/            # SQLAlchemy модели (Tables)
│   └── migrations/        # Alembic
├── schemas/               # Pydantic модели (DTO)
├── services/              # БИЗНЕС-ЛОГИКА (Самое важное)
│   ├── bitrix_service.py  # Общение с CRM
│   ├── parser_fuchs.py    # Логика с Groq (AI парсинг)
│   ├── sync_skf.py        # Логика работы с API SKF
│   └── pdf_service.py     # Генерация PDF
├── repositories/          # Работа с БД (CRUD)
│   ├── product_repo.py    # Сохранение товаров
│   └── user_repo.py
├── worker/                # Задачи Celery
│   └── tasks.py           # tasks.sync_skf_prices, tasks.process_email
└── main.py
```