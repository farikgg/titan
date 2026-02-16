from celery import Celery
from celery.schedules import crontab

from src.app.config import settings


# создает celery app
app = Celery(
    "tasks",
    broker=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0",
    backend=f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/1",
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Almaty",
    enable_utc=True,
    task_track_started=True,
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
}

app.conf.task_routes = {
    'src.worker.tasks.ai_process': {'queue': 'heavy'},
    'src.worker.tasks.generate_pdf_task': {'queue': 'heavy'},
    'src.worker.tasks.parse_from_fuchs': {'queue': 'default'},
    'src.worker.tasks.sync_skf_prices': {'queue': 'default'},
    'src.worker.tasks.sync_skf_single': {'queue': 'default'},
    'src.worker.tasks.process_deal_update': {'queue': 'default'},
    'src.worker.tasks.sync_skf_bulk': {'queue': 'default'},
}

# app.conf.worker_pool = "solo" # убрать на проде
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
