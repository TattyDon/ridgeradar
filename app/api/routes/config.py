"""Configuration API endpoints."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.config import get_settings
from app.models.domain import ConfigVersion

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigVersionResponse(BaseModel):
    """Config version response."""

    id: int
    config_type: str
    is_active: bool
    created_at: datetime
    created_by: str | None

    class Config:
        from_attributes = True


@router.get("/scoring")
async def get_scoring_config():
    """Get current scoring configuration."""
    settings = get_settings()
    defaults = settings.load_defaults_config()
    return defaults.get("scoring", {})


@router.get("/global")
async def get_global_config():
    """Get global configuration."""
    settings = get_settings()
    defaults = settings.load_defaults_config()
    return defaults.get("global", {})


@router.get("/versions", response_model=list[ConfigVersionResponse])
async def list_config_versions(
    db: AsyncSession = Depends(get_db),
    config_type: str | None = None,
):
    """List all config versions."""
    query = select(ConfigVersion).order_by(ConfigVersion.created_at.desc())
    if config_type:
        query = query.where(ConfigVersion.config_type == config_type)

    result = await db.execute(query)
    versions = result.scalars().all()

    return [
        ConfigVersionResponse(
            id=v.id,
            config_type=v.config_type,
            is_active=v.is_active,
            created_at=v.created_at,
            created_by=v.created_by,
        )
        for v in versions
    ]


@router.get("/versions/{version_id}")
async def get_config_version(
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get specific config version."""
    result = await db.execute(
        select(ConfigVersion).where(ConfigVersion.id == version_id)
    )
    version = result.scalar_one_or_none()

    if not version:
        raise HTTPException(status_code=404, detail="Config version not found")

    return {
        "id": version.id,
        "config_type": version.config_type,
        "config_data": version.config_data,
        "is_active": version.is_active,
        "created_at": version.created_at,
        "created_by": version.created_by,
    }
