"""
Celery application — standalone entry point for workers.
Configured for at-least-once delivery, idempotent tasks, and observability.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_init
from kombu import Exchange, Queue

from app.config import get_settings

settings = get_settings()

celery = Celery("aae")

celery.conf.update(
    broker_url=settings.CELERY_BROKER_URL,
    result_backend=settings.CELERY_RESULT_BACKEND,
    task_serializer=settings.CELERY_TASK_SERIALIZER,
    result_serializer=settings.CELERY_RESULT_SERIALIZER,
    accept_content=settings.CELERY_ACCEPT_CONTENT,
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_queues=(
        Queue("default", Exchange("default"), routing_key="default"),
        Queue("ocr", Exchange("ocr"), routing_key="ocr.#"),
        Queue("evaluation", Exchange("evaluation"), routing_key="evaluation.#"),
        Queue("notifications", Exchange("notifications"), routing_key="notifications.#"),
    ),
    task_routes={
        "app.tasks.ocr.*": {"queue": "ocr"},
        "app.tasks.evaluation.*": {"queue": "evaluation"},
        "app.tasks.notifications.*": {"queue": "notifications"},
    },
    beat_schedule={},
)

celery.autodiscover_tasks(["app.tasks"])


@worker_init.connect
def on_worker_init(**_kwargs):
    """Bootstrap per-worker resources (DB pools, etc.)."""
    init_settings = get_settings()
    from app.extensions import init_mongo, init_redis

    init_mongo(
        init_settings.MONGO_URI,
        maxPoolSize=init_settings.MONGO_MAX_POOL_SIZE,
    )
    init_redis(init_settings.REDIS_URL)
