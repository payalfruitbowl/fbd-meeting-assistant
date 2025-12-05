"""
Celery application configuration for background tasks.
"""
import os
import logging
import ssl
from celery import Celery

logger = logging.getLogger(__name__)

# Upstash Redis connection URL with SSL parameters (hardcoded as requested)
# Using URL parameters to specify SSL settings
REDIS_URL = "rediss://default:AZadAAIncDJiNmZmZWY4Yjc0MmQ0MTdlODcyOWZlYjM4YjhmNzY2Y3AyMzg1NTc@calm-piglet-38557.upstash.io:6379?ssl_cert_reqs=CERT_NONE"

# Create Celery app
celery_app = Celery(
    "fruitbowl",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks"]  # Will contain our tasks
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # 55 minutes soft limit
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks to prevent memory leaks
)

logger.info("Celery app configured with Upstash Redis")

