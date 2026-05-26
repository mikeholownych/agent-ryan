from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ryan.config import Settings, get_settings
from ryan.readiness.service import check_production_readiness

router = APIRouter(prefix="/api/production", tags=["production"])


class ProductionReadinessResponse(BaseModel):
    ready: bool
    blockers: list[str]
    decisions: dict[str, str]


@router.get("/readiness", response_model=ProductionReadinessResponse)
def get_production_readiness(settings: Settings = Depends(get_settings)):
    return check_production_readiness(settings)


__all__ = ["router"]
