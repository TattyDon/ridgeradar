"""Celery tasks for RidgeRadar.

This module configures Celery and registers all periodic tasks.
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

# Create Celery application
celery_app = Celery(
    "ridgeradar",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.discovery",
        "app.tasks.snapshots",
        "app.tasks.profiling",
        "app.tasks.scoring",
        "app.tasks.competition_stats",
        "app.tasks.market_closure",
        "app.tasks.results",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Task behavior
    task_track_started=True,
    task_time_limit=600,  # 10 minute hard limit
    task_soft_time_limit=540,  # 9 minute soft limit
    # Result expiration
    result_expires=3600,  # 1 hour
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
)

# Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    # Market discovery - every 15 minutes
    "discover-markets": {
        "task": "app.tasks.discovery.discover_markets",
        "schedule": 900.0,  # 15 minutes
        "options": {"expires": 840},  # Expire before next run
    },
    # Snapshot capture - every 60 seconds
    "capture-snapshots": {
        "task": "app.tasks.snapshots.capture_snapshots",
        "schedule": 60.0,
        "options": {"expires": 55},
    },
    # Daily profiling - every hour at :05
    "compute-profiles": {
        "task": "app.tasks.profiling.compute_daily_profiles",
        "schedule": crontab(minute=5),  # Every hour at :05
        "options": {"expires": 3540},
    },
    # Scoring - every 5 minutes
    "score-markets": {
        "task": "app.tasks.scoring.score_markets",
        "schedule": 300.0,  # 5 minutes
        "options": {"expires": 280},
    },
    # Competition stats aggregation - every hour at :30
    "aggregate-competition-stats": {
        "task": "aggregate_competition_stats",
        "schedule": crontab(minute=30),  # Every hour at :30
        "options": {"expires": 3540},
    },
    # Market closure - capture closing odds every 2 minutes
    "capture-closing-data": {
        "task": "app.tasks.market_closure.capture_closing_data_task",
        "schedule": 120.0,  # 2 minutes
        "options": {"expires": 110},
    },
    # Results capture - check for settlements every 15 minutes
    "capture-results": {
        "task": "app.tasks.market_closure.capture_results_task",
        "schedule": 900.0,  # 15 minutes
        "options": {"expires": 840},
    },
    # Event results - capture match outcomes every 30 minutes
    "capture-event-results": {
        "task": "app.tasks.results.capture_event_results_task",
        "schedule": 1800.0,  # 30 minutes
        "options": {"expires": 1740},
    },
    # Enhance results with Correct Score data every hour at :45
    "update-results-from-scores": {
        "task": "app.tasks.results.update_results_from_scores_task",
        "schedule": crontab(minute=45),  # Every hour at :45
        "options": {"expires": 3540},
    },
}
