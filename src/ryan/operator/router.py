from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ryan.db import get_session
from ryan.exceptions import ExceptionRecordError, transition_exception_status
from ryan.kill_switch import (
    activate_kill_switch,
    deactivate_kill_switch,
    get_kill_switch_state,
)
from ryan.models import ExceptionRecord, LedgerEntry, PolicyDecision, Report, Wallet

router = APIRouter(prefix="/api/operator", tags=["operator"])


class OperatorActionRequest(BaseModel):
    actor: str
    reason: str


class ExceptionStatusRequest(BaseModel):
    status: str
    actor: str
    reason: str


@router.get("/console")
def get_operator_console(session: Session = Depends(get_session)) -> dict[str, Any]:
    latest_report = session.scalar(
        select(Report).where(Report.type == "daily").order_by(Report.generated_at.desc())
    )
    return {
        "wallets": [
            _wallet_payload(wallet)
            for wallet in session.scalars(select(Wallet).order_by(Wallet.type.asc()))
        ],
        "recent_actions": [
            _ledger_payload(entry)
            for entry in session.scalars(
                select(LedgerEntry).order_by(LedgerEntry.timestamp.desc()).limit(10)
            )
        ],
        "policy_decisions": [
            _policy_decision_payload(decision)
            for decision in session.scalars(
                select(PolicyDecision)
                .order_by(PolicyDecision.created_at.desc())
                .limit(10)
            )
        ],
        "exceptions": [
            _exception_payload(exception)
            for exception in session.scalars(
                select(ExceptionRecord)
                .where(ExceptionRecord.status == "open")
                .order_by(ExceptionRecord.created_at.asc())
            )
        ],
        "daily_pnl": latest_report.summary if latest_report is not None else {},
        "kill_switch": _kill_switch_payload(get_kill_switch_state(session)),
    }


@router.post("/kill-switch/activate")
def post_operator_kill_switch_activate(
    payload: OperatorActionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    state = activate_kill_switch(
        session,
        actor=payload.actor,
        reason=payload.reason,
    )
    session.commit()
    session.refresh(state)
    return _kill_switch_payload(state)


@router.post("/kill-switch/deactivate")
def post_operator_kill_switch_deactivate(
    payload: OperatorActionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    state = deactivate_kill_switch(
        session,
        actor=payload.actor,
        reason=payload.reason,
    )
    session.commit()
    session.refresh(state)
    return _kill_switch_payload(state)


@router.post("/exceptions/{exception_id}/status")
def post_operator_exception_status(
    exception_id: str,
    payload: ExceptionStatusRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        exception = transition_exception_status(
            session,
            exception_id=exception_id,
            status=payload.status,
            actor=payload.actor,
            reason=payload.reason,
        )
    except ExceptionRecordError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    session.commit()
    session.refresh(exception)
    return _exception_payload(exception)


def _wallet_payload(wallet: Wallet) -> dict[str, Any]:
    return {
        "id": wallet.id,
        "type": wallet.type,
        "balance": str(wallet.balance),
        "currency": wallet.currency,
        "locked": wallet.locked,
        "limits": wallet.limits,
    }


def _ledger_payload(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "type": entry.type,
        "reference_type": entry.reference_type,
        "reference_id": entry.reference_id,
        "actor": entry.actor,
    }


def _policy_decision_payload(decision: PolicyDecision) -> dict[str, Any]:
    return {
        "id": decision.id,
        "action_type": decision.action_type,
        "decision": decision.decision,
        "reason": decision.reason,
        "actor": decision.actor,
    }


def _exception_payload(exception: ExceptionRecord) -> dict[str, Any]:
    return {
        "id": exception.id,
        "type": exception.type,
        "severity": exception.severity,
        "status": exception.status,
        "reason": exception.reason,
        "reference_type": exception.reference_type,
        "reference_id": exception.reference_id,
    }


def _kill_switch_payload(state) -> dict[str, Any]:
    return {
        "id": state.id,
        "active": state.active,
        "reason": state.reason,
    }


__all__ = ["router"]
