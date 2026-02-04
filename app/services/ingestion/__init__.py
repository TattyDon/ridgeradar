"""Ingestion module for RidgeRadar."""

from app.services.ingestion.discovery import MarketDiscoveryService, classify_competition_tier
from app.services.ingestion.snapshots import SnapshotCaptureService

__all__ = [
    "MarketDiscoveryService",
    "SnapshotCaptureService",
    "classify_competition_tier",
]
