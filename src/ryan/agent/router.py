from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ryan.catalog import list_approved_offers
from ryan.db import get_session
from ryan.expenses import ExpenseRequestError, create_expense_request
from ryan.kill_switch import get_kill_switch_state
from ryan.ledger import append_ledger_entry
from ryan.models import Agent, ExceptionRecord, ExpenseRequest, LedgerEntry, Wallet

router = APIRouter(tags=["agent"])


class PlanRequest(BaseModel):
    actor: str
    objective: str


class ExecuteRequest(BaseModel):
    action_type: str
    vendor: str | None = None
    category: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    rationale: str | None = None
    actor: str
    idempotency_key: str
    timestamp: datetime | None = None
    irreversible: bool = False


@router.post("/api/plan")
def post_plan(payload: PlanRequest, session: Session = Depends(get_session)):
    kill_switch = get_kill_switch_state(session)
    offers = list_approved_offers(session)
    proposed_actions = [
        {
            "action_type": "select_offer",
            "offer_id": offer.id,
            "name": offer.name,
            "allowed_channels": offer.allowed_channels,
        }
        for offer in offers
    ]
    plan_entry = append_ledger_entry(
        session,
        type="audit.agent.planned",
        amount=None,
        currency=None,
        reference_type="agent_plan",
        reference_id=payload.objective,
        actor=payload.actor,
        metadata={
            "objective": payload.objective,
            "read_only": kill_switch.active,
            "proposed_actions": proposed_actions,
        },
    )
    session.commit()
    return {
        "plan_id": plan_entry.id,
        "read_only": kill_switch.active,
        "objective": payload.objective,
        "proposed_actions": proposed_actions,
    }


@router.post("/api/execute")
def post_execute(payload: ExecuteRequest, session: Session = Depends(get_session)):
    if payload.action_type != "expense_request":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported agent action {payload.action_type!r}",
        )
    if (
        payload.vendor is None
        or payload.category is None
        or payload.amount is None
        or payload.currency is None
        or payload.rationale is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expense execution requires vendor, category, amount, currency, rationale",
        )
    try:
        expense = create_expense_request(
            session,
            vendor=payload.vendor,
            category=payload.category,
            amount=payload.amount,
            currency=payload.currency,
            rationale=payload.rationale,
            actor=payload.actor,
            idempotency_key=payload.idempotency_key,
            timestamp=payload.timestamp,
            irreversible=payload.irreversible,
        )
    except ExpenseRequestError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    session.commit()
    session.refresh(expense)
    return {
        "expense_id": expense.id,
        "outcome": _expense_outcome(expense),
        "policy_status": expense.policy_status,
        "execution_status": expense.execution_status,
    }


@router.get("/api/status")
def get_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    agent = session.scalar(select(Agent).order_by(Agent.created_at.asc()).limit(1))
    kill_switch = get_kill_switch_state(session)
    return {
        "agent_status": agent.status if agent is not None else "unknown",
        "mode": agent.mode if agent is not None else "unknown",
        "current_objective": agent.current_objective if agent is not None else None,
        "active_offers": [
            {
                "id": offer.id,
                "name": offer.name,
                "price": str(offer.price),
                "currency": offer.currency,
                "allowed_channels": offer.allowed_channels,
            }
            for offer in list_approved_offers(session)
        ],
        "wallet_budget_state": {
            wallet.type: {
                "balance": str(wallet.balance),
                "currency": wallet.currency,
                "locked": wallet.locked,
                "limits": wallet.limits,
            }
            for wallet in session.scalars(select(Wallet))
        },
        "pending_tasks": _pending_tasks(session),
        "recent_outcomes": _recent_outcomes(session),
        "kill_switch": {
            "active": kill_switch.active,
            "reason": kill_switch.reason,
        },
        "exception_count": session.scalar(
            select(func.count(ExceptionRecord.id)).where(ExceptionRecord.status == "open")
        ),
    }


@router.get("/api/agent/console")
def get_agent_console(session: Session = Depends(get_session)) -> dict[str, Any]:
    status_payload = get_status(session)
    operating_wallet = session.scalar(
        select(Wallet).where(Wallet.type == "operating").limit(1)
    )
    return {
        "current_objective": status_payload["current_objective"],
        "approved_offer_set": status_payload["active_offers"],
        "pending_tasks": status_payload["pending_tasks"],
        "allowed_spend": _allowed_spend_payload(operating_wallet),
        "recent_outcomes": status_payload["recent_outcomes"],
        "budget_state": status_payload["wallet_budget_state"],
        "kill_switch": status_payload["kill_switch"],
    }


def _expense_outcome(expense: ExpenseRequest) -> str:
    if expense.execution_status == "executed":
        return "executed"
    if expense.execution_status == "pending_review":
        return "pending_review"
    return "blocked"


def _allowed_spend_payload(wallet: Wallet | None) -> dict[str, Any]:
    if wallet is None:
        return {"available": "0.00", "currency": None}
    minimum = Decimal(str(wallet.limits.get("minimum", "0.00")))
    available = wallet.balance - minimum
    if available < Decimal("0.00"):
        available = Decimal("0.00")
    return {
        "available": str(available),
        "currency": wallet.currency,
    }


def _pending_tasks(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "id": exception.id,
            "type": exception.type,
            "reason": exception.reason,
        }
        for exception in session.scalars(
            select(ExceptionRecord).where(ExceptionRecord.status == "open")
        )
    ]


def _recent_outcomes(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "id": entry.id,
            "type": entry.type,
            "reference_type": entry.reference_type,
            "reference_id": entry.reference_id,
        }
        for entry in session.scalars(
            select(LedgerEntry).order_by(LedgerEntry.timestamp.desc()).limit(10)
        )
    ]


__all__ = ["router"]
