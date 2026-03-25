from celery import Celery
from celery.schedules import crontab

from src.app.config import settings


# создаёт celery app
# Если задан REDIS_URL (с учётом логина/пароля) — используем его как broker и backend.
# Иначе собираем URL из REDIS_HOST/REDIS_PORT.
if settings.REDIS_URL:
    broker_url = settings.REDIS_URL
else:
    broker_url = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"

app = Celery("tasks", broker=broker_url, backend=broker_url)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Almaty",
    enable_utc=True,
    task_track_started=True,
    task_ignore_result=False,
    result_backend=broker_url,
    result_persistent=True,
    # 1 воркер = 1 задача
    worker_prefetch_multiplier=1,
)

# celery app-ка автоматический смотрит на таски
app.autodiscover_tasks(["src.worker.tasks"])

app.conf.beat_schedule = {
    'parser_email_every_three_month': {
        'task': 'src.worker.tasks.parse_from_fuchs',
        'schedule': crontab(day_of_month=1, month_of_year='*/3', hour=3, minute=0), # каждый 3 месяц 1 числа в 3 часа ночи запустает парсинг таск
    },
    'parser_requests_every_hour': {
        'task': 'src.worker.tasks.parse_from_requests',
        'schedule': crontab(minute='*/1'),  # Каждую минуту
    },
    # Каждый день в 09:00 по Asia/Almaty — отчёт по просроченным/истекающим ценам FUCHS
    'fuchs_price_expiry_report_daily': {
        'task': 'src.worker.tasks.send_fuchs_price_expiry_report',
        'schedule': crontab(hour=9, minute=0),
    },
    # Каждый час — обновление статусов (expired/expiring_soon) в БД
    'sync_price_statuses_hourly': {
        'task': 'src.worker.tasks.sync_price_statuses',
        'schedule': crontab(minute=0),
    },
}

app.conf.task_routes = {
    'src.worker.tasks.ai_process': {'queue': 'heavy'},
    'src.worker.tasks.generate_pdf_task': {'queue': 'heavy'},
    'src.worker.tasks.parse_from_fuchs': {'queue': 'default'},
    'src.worker.tasks.parse_from_requests': {'queue': 'default'},
    'src.worker.tasks.requests_process': {'queue': 'default'},
    'src.worker.tasks.sync_skf_prices': {'queue': 'default'},
    'src.worker.tasks.sync_skf_single': {'queue': 'default'},
    'src.worker.tasks.process_deal_update': {'queue': 'default'},
    'src.worker.tasks.sync_skf_bulk': {'queue': 'default'},
    'src.worker.tasks.send_fuchs_price_expiry_report': {'queue': 'default'},
    'src.worker.tasks.sync_price_statuses': {'queue': 'default'},
}

# app.conf.worker_pool = "solo" # убрать на проде
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
