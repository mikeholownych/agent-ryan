from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ryan.db import get_session
from ryan.wallets.service import (
    WalletPolicyError,
    WalletTransferError,
    WalletNotFoundError,
    freeze_wallet,
    list_wallets,
    transfer_between_wallets,
    unfreeze_wallet,
)

router = APIRouter(prefix="/api/wallets", tags=["wallets"])


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    balance: Decimal
    currency: str
    locked: bool
    limits: dict[str, Any]


class WalletFreezeRequest(BaseModel):
    wallet_id: str
    actor: str
    reason: str


class WalletTransferRequest(BaseModel):
    source_wallet_id: str
    destination_wallet_id: str
    amount: Decimal
    currency: str
    actor: str
    reason: str
    policy_decision_id: str
    idempotency_key: str


class WalletTransferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_wallet_id: str
    destination_wallet_id: str
    amount: Decimal
    currency: str
    status: str
    reason: str
    policy_decision_id: str | None
    idempotency_key: str | None


@router.get("", response_model=list[WalletResponse])
def get_wallets(session: Session = Depends(get_session)):
    return list_wallets(session)


@router.post("/freeze", response_model=WalletResponse)
def post_wallet_freeze(
    payload: WalletFreezeRequest,
    session: Session = Depends(get_session),
):
    try:
        wallet = freeze_wallet(
            session,
            wallet_id=payload.wallet_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except WalletNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    session.commit()
    session.refresh(wallet)
    return wallet


@router.post("/unfreeze", response_model=WalletResponse)
def post_wallet_unfreeze(
    payload: WalletFreezeRequest,
    session: Session = Depends(get_session),
):
    try:
        wallet = unfreeze_wallet(
            session,
            wallet_id=payload.wallet_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except WalletNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    session.commit()
    session.refresh(wallet)
    return wallet


@router.post(
    "/transfer",
    response_model=WalletTransferResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_wallet_transfer(
    payload: WalletTransferRequest,
    session: Session = Depends(get_session),
):
    try:
        transfer = transfer_between_wallets(
            session,
            source_wallet_id=payload.source_wallet_id,
            destination_wallet_id=payload.destination_wallet_id,
            amount=payload.amount,
            currency=payload.currency,
            actor=payload.actor,
            reason=payload.reason,
            policy_decision_id=payload.policy_decision_id,
            idempotency_key=payload.idempotency_key,
        )
    except WalletPolicyError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error))
    except WalletNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except WalletTransferError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    session.commit()
    session.refresh(transfer)
    return transfer


__all__ = ["router"]
