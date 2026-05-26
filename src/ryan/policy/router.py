from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ryan.db import get_session
from ryan.policy.service import (
    PolicyEvaluationRequest,
    create_policy_rule,
    evaluate_policy,
    list_policy_rules,
)

router = APIRouter(prefix="/api/policy", tags=["policy"])


class PolicyRuleCreateRequest(BaseModel):
    type: str
    configuration: dict[str, Any]
    actor: str
    status: str = "active"
    priority: int = 100


class PolicyRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    configuration: dict[str, Any]
    priority: int
    created_by_actor: str


class PolicyEvaluateRequest(BaseModel):
    action_type: str
    vendor: str | None = None
    category: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    actor: str
    request_reference_type: str
    request_reference_id: str
    source_wallet_type: str = "operating"
    irreversible: bool = False
    timestamp: datetime | None = None


class PolicyDecisionResponse(BaseModel):
    id: str
    action_type: str
    decision: str
    reason: str
    rule_results: dict[str, Any]
    request_reference_type: str
    request_reference_id: str
    actor: str


@router.get("/rules", response_model=list[PolicyRuleResponse])
def get_policy_rules(session: Session = Depends(get_session)) -> list:
    return list_policy_rules(session)


@router.post(
    "/rules",
    response_model=PolicyRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_policy_rule(
    payload: PolicyRuleCreateRequest,
    session: Session = Depends(get_session),
):
    rule = create_policy_rule(
        session,
        rule_type=payload.type,
        configuration=payload.configuration,
        actor=payload.actor,
        status=payload.status,
        priority=payload.priority,
    )
    session.commit()
    session.refresh(rule)
    return rule


@router.post("/evaluate", response_model=PolicyDecisionResponse)
def post_policy_evaluate(
    payload: PolicyEvaluateRequest,
    session: Session = Depends(get_session),
):
    decision = evaluate_policy(
        session,
        request=PolicyEvaluationRequest(
            action_type=payload.action_type,
            vendor=payload.vendor,
            category=payload.category,
            amount=payload.amount,
            currency=payload.currency,
            actor=payload.actor,
            request_reference_type=payload.request_reference_type,
            request_reference_id=payload.request_reference_id,
            source_wallet_type=payload.source_wallet_type,
            irreversible=payload.irreversible,
        ),
        timestamp=payload.timestamp,
    )
    session.commit()
    session.refresh(decision)
    return decision


__all__ = ["router"]
