from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ryan.db import get_session
from ryan.reports.service import generate_daily_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    summary: dict[str, Any]


@router.get("/daily", response_model=ReportResponse)
def get_daily_report(
    date: date,
    actor: str = "operator",
    session: Session = Depends(get_session),
):
    report = generate_daily_report(session, report_date=date, actor=actor)
    session.commit()
    session.refresh(report)
    return report


__all__ = ["router"]
