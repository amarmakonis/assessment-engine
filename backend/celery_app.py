import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# Use environment variable for Redis URI, default to localhost for Docker Compose setup
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "ocrv2",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Ensure tasks are acknowledged only after they are completed
    task_acks_late=True,
    # Optimize for multiple small tasks
    worker_prefetch_multiplier=1
)

# Alias for systemd / docs that use `celery -A celery_app.celery`
celery = celery_app

if __name__ == "__main__":
    celery_app.start()
