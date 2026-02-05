"""Admin API endpoints.

Provides manual task triggers and system administration functions.
These endpoints should be protected in production (not implemented here).
"""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = structlog.get_logger(__name__)


class TaskTriggerResponse(BaseModel):
    """Response from task trigger."""
    task_name: str
    task_id: str
    status: str
    message: str


# Map of friendly names to actual Celery task names
TASK_MAP = {
    # Phase 1 tasks
    "capture-closing-data": "app.tasks.market_closure.capture_closing_data_task",
    "capture-results": "app.tasks.market_closure.capture_results_task",
    "capture-event-results": "app.tasks.results.capture_event_results_task",
    "update-results-from-scores": "app.tasks.results.update_results_from_scores_task",
    "discover-markets": "app.tasks.discovery.discover_markets",
    "capture-snapshots": "app.tasks.snapshots.capture_snapshots",
    "compute-profiles": "app.tasks.profiling.compute_daily_profiles",
    "score-markets": "app.tasks.scoring.score_markets",
    # Phase 2 shadow trading tasks
    "check-phase-status": "app.tasks.shadow_trading.check_phase_status_task",
    "make-shadow-decisions": "app.tasks.shadow_trading.make_shadow_decisions_task",
    "capture-shadow-closing-prices": "app.tasks.shadow_trading.capture_closing_prices_task",
    "settle-shadow-decisions": "app.tasks.shadow_trading.settle_shadow_decisions_task",
}


@router.post("/trigger-task/{task_name}", response_model=TaskTriggerResponse)
async def trigger_task(task_name: str) -> TaskTriggerResponse:
    """
    Manually trigger a background task.

    Available tasks:
    - capture-closing-data: Capture closing odds for markets starting soon
    - capture-results: Capture settlement results for closed markets
    - capture-event-results: Capture actual match scores
    - update-results-from-scores: Enhance results with Correct Score data
    - discover-markets: Discover new markets from Betfair
    - capture-snapshots: Capture market snapshots
    - compute-profiles: Compute daily market profiles
    - score-markets: Calculate exploitability scores
    """
    if task_name not in TASK_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown task: {task_name}. Available: {list(TASK_MAP.keys())}"
        )

    celery_task_name = TASK_MAP[task_name]

    try:
        # Import celery app and send task
        from app.tasks import celery_app

        result = celery_app.send_task(celery_task_name)

        logger.info(
            "task_triggered_manually",
            task_name=task_name,
            celery_task=celery_task_name,
            task_id=result.id,
        )

        return TaskTriggerResponse(
            task_name=task_name,
            task_id=result.id,
            status="submitted",
            message=f"Task {task_name} submitted successfully. Check Celery logs for progress."
        )

    except Exception as e:
        logger.error(
            "task_trigger_failed",
            task_name=task_name,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger task: {str(e)}"
        )


@router.get("/tasks", response_model=dict[str, str])
async def list_tasks() -> dict[str, str]:
    """List all available tasks that can be triggered manually."""
    return TASK_MAP
