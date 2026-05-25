from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ryan.kill_switch import KillSwitchActiveError, assert_external_action_allowed
from ryan.models import ExpenseRequest, PolicyDecision, PolicyRule, Wallet
from ryan.telemetry import emit_alert, emit_policy_event


APPROVED_EXPENSE_STATUSES = frozenset({"approved", "executed"})
REQUIRED_POLICY_RULE_TYPES = frozenset(
    {
        "vendor_allowlist",
        "spend_threshold",
        "category_budget",
        "time_window",
        "revenue_floor",
        "reserve_minimum",
    }
)


@dataclass(frozen=True)
class PolicyEvaluationRequest:
    action_type: str
    vendor: str | None
    category: str | None
    amount: Decimal | None
    currency: str | None
    actor: str
    request_reference_type: str
    request_reference_id: str
    source_wallet_type: str = "operating"
    irreversible: bool = False


def create_policy_rule(
    session: Session,
    *,
    rule_type: str,
    configuration: dict[str, Any],
    actor: str,
    status: str = "active",
    priority: int = 100,
) -> PolicyRule:
    rule = PolicyRule(
        type=rule_type,
        status=status,
        configuration=_json_safe(configuration),
        priority=priority,
        created_by_actor=actor,
    )
    session.add(rule)
    session.flush()
    return rule


def list_policy_rules(
    session: Session,
    *,
    active_only: bool = True,
) -> list[PolicyRule]:
    statement = select(PolicyRule)
    if active_only:
        statement = statement.where(PolicyRule.status == "active")
    return list(
        session.scalars(
            statement.order_by(PolicyRule.priority.asc(), PolicyRule.created_at.asc())
        ).all()
    )


def evaluate_policy(
    session: Session,
    *,
    request: PolicyEvaluationRequest,
    timestamp: datetime | None = None,
) -> PolicyDecision:
    occurred_at = timestamp or datetime.now(UTC)
    rule_results: dict[str, Any] = {}

    try:
        assert_external_action_allowed(session, action_type=request.action_type)
    except KillSwitchActiveError as error:
        rule_results["kill_switch"] = {
            "passed": False,
            "decision": "reject",
            "reason": str(error),
            "kill_switch_state_id": error.kill_switch_state_id,
        }
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=str(error),
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    rule_results["kill_switch"] = {
        "passed": True,
        "decision": "continue",
        "reason": "kill switch is inactive for this action",
    }

    missing_input = _first_missing_required_input(request)
    if missing_input is not None:
        rule_results["required_inputs"] = {
            "passed": False,
            "decision": "reject",
            "reason": f"missing required policy input: {missing_input}",
        }
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=f"missing required policy input: {missing_input}",
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    rules = _active_rules_by_type(session)
    missing_rules = sorted(REQUIRED_POLICY_RULE_TYPES - set(rules))
    if missing_rules:
        reason = "missing active policy rule: " + ", ".join(missing_rules)
        rule_results["policy_config"] = {
            "passed": False,
            "decision": "reject",
            "reason": reason,
        }
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=reason,
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    source_wallet = _wallet_by_type_and_currency(
        session,
        wallet_type=request.source_wallet_type,
        currency=request.currency,
    )
    if source_wallet is None:
        reason = (
            "missing source wallet for policy evaluation: "
            f"{request.source_wallet_type}/{request.currency}"
        )
        rule_results["wallet_lock"] = {
            "passed": False,
            "decision": "reject",
            "reason": reason,
        }
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=reason,
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    if source_wallet.locked:
        reason = "source wallet is locked or frozen"
        rule_results["wallet_lock"] = {
            "passed": False,
            "decision": "reject",
            "reason": reason,
            "wallet_id": source_wallet.id,
        }
        decision = _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=reason,
            rule_results=rule_results,
            timestamp=occurred_at,
        )
        _emit_policy_alert(
            session,
            alert_type="frozen_spend_attempt",
            severity="high",
            decision=decision,
            request=request,
            reason=reason,
            timestamp=occurred_at,
        )
        return decision

    rule_results["wallet_lock"] = {
        "passed": True,
        "decision": "continue",
        "reason": "source wallet is not locked or frozen",
        "wallet_id": source_wallet.id,
    }

    vendor_result = _evaluate_vendor_allowlist(rules["vendor_allowlist"], request)
    rule_results["vendor_allowlist"] = vendor_result
    if not vendor_result["passed"]:
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=vendor_result["reason"],
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    time_window_result = _evaluate_time_window(
        rules["time_window"],
        occurred_at,
    )
    rule_results["time_window"] = time_window_result
    if not time_window_result["passed"]:
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=time_window_result["reason"],
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    revenue_floor_result = _evaluate_revenue_floor(
        session,
        rules["revenue_floor"],
        request,
    )
    rule_results["revenue_floor"] = revenue_floor_result
    if not revenue_floor_result["passed"]:
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=revenue_floor_result["reason"],
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    reserve_minimum_result = _evaluate_reserve_minimum(
        rules["reserve_minimum"],
        request,
        source_wallet,
    )
    rule_results["reserve_minimum"] = reserve_minimum_result
    if not reserve_minimum_result["passed"]:
        decision = _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=reserve_minimum_result["reason"],
            rule_results=rule_results,
            timestamp=occurred_at,
        )
        _emit_policy_alert(
            session,
            alert_type="budget_exhaustion",
            severity="high",
            decision=decision,
            request=request,
            reason=reserve_minimum_result["reason"],
            timestamp=occurred_at,
        )
        return decision

    category_budget_result = _evaluate_category_budget(
        session,
        rules["category_budget"],
        request,
    )
    rule_results["category_budget"] = category_budget_result
    if not category_budget_result["passed"]:
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=category_budget_result["reason"],
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    spend_threshold_result = _evaluate_spend_threshold(
        rules["spend_threshold"],
        request,
    )
    rule_results["spend_threshold"] = spend_threshold_result
    if spend_threshold_result["decision"] == "reject":
        return _persist_decision(
            session,
            request=request,
            decision="reject",
            reason=spend_threshold_result["reason"],
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    escalation_reasons: list[str] = []
    if not spend_threshold_result["passed"]:
        escalation_reasons.append(spend_threshold_result["reason"])
    if request.irreversible:
        escalation_reasons.append("irreversible action requires operator review")

    if escalation_reasons:
        reason = "; ".join(escalation_reasons)
        rule_results["exception_escalation"] = {
            "passed": False,
            "decision": "escalate",
            "reason": reason,
        }
        return _persist_decision(
            session,
            request=request,
            decision="escalate",
            reason=reason,
            rule_results=rule_results,
            timestamp=occurred_at,
        )

    rule_results["exception_escalation"] = {
        "passed": True,
        "decision": "approve",
        "reason": "no escalation condition matched",
    }
    return _persist_decision(
        session,
        request=request,
        decision="approve",
        reason="approved by deterministic policy evaluation",
        rule_results=rule_results,
        timestamp=occurred_at,
    )


def _persist_decision(
    session: Session,
    *,
    request: PolicyEvaluationRequest,
    decision: str,
    reason: str,
    rule_results: dict[str, Any],
    timestamp: datetime,
) -> PolicyDecision:
    policy_decision = PolicyDecision(
        action_type=request.action_type,
        decision=decision,
        reason=reason,
        rule_results=_json_safe(rule_results),
        request_reference_type=request.request_reference_type,
        request_reference_id=request.request_reference_id,
        actor=request.actor,
    )
    session.add(policy_decision)
    session.flush()

    emit_policy_event(
        session,
        event_name="evaluated",
        policy_decision_id=policy_decision.id,
        actor=request.actor,
        metadata={
            "decision": decision,
            "reason": reason,
            "action_type": request.action_type,
            "request_reference_type": request.request_reference_type,
            "request_reference_id": request.request_reference_id,
        },
        timestamp=timestamp,
    )
    return policy_decision


def _emit_policy_alert(
    session: Session,
    *,
    alert_type: str,
    severity: str,
    decision: PolicyDecision,
    request: PolicyEvaluationRequest,
    reason: str,
    timestamp: datetime,
) -> None:
    emit_alert(
        session,
        alert_type=alert_type,
        severity=severity,
        actor=request.actor,
        reference_type="policy_decision",
        reference_id=decision.id,
        metadata={
            "reason": reason,
            "action_type": request.action_type,
            "request_reference_type": request.request_reference_type,
            "request_reference_id": request.request_reference_id,
        },
        timestamp=timestamp,
    )


def _first_missing_required_input(
    request: PolicyEvaluationRequest,
) -> str | None:
    required_values = {
        "action_type": request.action_type,
        "vendor": request.vendor,
        "category": request.category,
        "amount": request.amount,
        "currency": request.currency,
        "actor": request.actor,
        "request_reference_type": request.request_reference_type,
        "request_reference_id": request.request_reference_id,
        "source_wallet_type": request.source_wallet_type,
    }
    for field_name, value in required_values.items():
        if value is None or value == "":
            return field_name
    if request.amount <= Decimal("0"):
        return "amount"
    return None


def _active_rules_by_type(session: Session) -> dict[str, PolicyRule]:
    rules: dict[str, PolicyRule] = {}
    for rule in list_policy_rules(session):
        rules.setdefault(rule.type, rule)
    return rules


def _wallet_by_type_and_currency(
    session: Session,
    *,
    wallet_type: str,
    currency: str,
) -> Wallet | None:
    return session.scalar(
        select(Wallet).where(Wallet.type == wallet_type, Wallet.currency == currency)
    )


def _evaluate_vendor_allowlist(
    rule: PolicyRule,
    request: PolicyEvaluationRequest,
) -> dict[str, Any]:
    vendors = rule.configuration.get("vendors") or []
    approved_vendors = [
        vendor
        for vendor in vendors
        if vendor.get("status", "approved") == "approved"
    ]
    for vendor in approved_vendors:
        if vendor.get("name") == request.vendor and request.category in (
            vendor.get("categories") or []
        ):
            return {
                "passed": True,
                "decision": "continue",
                "reason": "vendor and category are allowlisted",
                "vendor": request.vendor,
                "category": request.category,
            }

    return {
        "passed": False,
        "decision": "reject",
        "reason": "vendor is not allowlisted for requested category",
        "vendor": request.vendor,
        "category": request.category,
    }


def _evaluate_spend_threshold(
    rule: PolicyRule,
    request: PolicyEvaluationRequest,
) -> dict[str, Any]:
    cap = _decimal_from_config(rule.configuration.get("per_transaction_cap"))
    if cap is None or rule.configuration.get("currency") != request.currency:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "spend threshold rule is missing required currency or cap",
        }

    if request.amount > cap:
        return {
            "passed": False,
            "decision": "escalate",
            "reason": "amount exceeds autonomous spend threshold",
            "amount": str(request.amount),
            "cap": str(cap),
        }

    return {
        "passed": True,
        "decision": "continue",
        "reason": "amount is within autonomous spend threshold",
        "amount": str(request.amount),
        "cap": str(cap),
    }


def _evaluate_category_budget(
    session: Session,
    rule: PolicyRule,
    request: PolicyEvaluationRequest,
) -> dict[str, Any]:
    budget = _matching_category_budget(rule, request)
    if budget is None:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "missing category budget for requested category and currency",
            "category": request.category,
            "currency": request.currency,
        }

    limit = _decimal_from_config(budget.get("limit"))
    if limit is None:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "category budget rule is missing a valid limit",
            "category": request.category,
        }

    current_spend = session.scalar(
        select(func.coalesce(func.sum(ExpenseRequest.amount), Decimal("0.00"))).where(
            ExpenseRequest.category == request.category,
            ExpenseRequest.currency == request.currency,
            ExpenseRequest.policy_status.in_(APPROVED_EXPENSE_STATUSES),
        )
    )
    projected_spend = Decimal(current_spend or Decimal("0.00")) + request.amount
    if projected_spend > limit:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "category budget would be exceeded; rejecting fail-closed",
            "category": request.category,
            "current_spend": str(current_spend),
            "requested_amount": str(request.amount),
            "projected_spend": str(projected_spend),
            "limit": str(limit),
        }

    return {
        "passed": True,
        "decision": "continue",
        "reason": "category budget remains available",
        "category": request.category,
        "current_spend": str(current_spend),
        "projected_spend": str(projected_spend),
        "limit": str(limit),
    }


def _matching_category_budget(
    rule: PolicyRule,
    request: PolicyEvaluationRequest,
) -> dict[str, Any] | None:
    for budget in rule.configuration.get("budgets") or []:
        if (
            budget.get("category") == request.category
            and budget.get("currency") == request.currency
        ):
            return budget
    return None


def _evaluate_time_window(
    rule: PolicyRule,
    timestamp: datetime,
) -> dict[str, Any]:
    occurred_at = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
    day = occurred_at.strftime("%a").lower()[:3]
    for window in rule.configuration.get("windows") or []:
        start_hour = window.get("start_hour_utc")
        end_hour = window.get("end_hour_utc")
        if (
            day in (window.get("days") or [])
            and isinstance(start_hour, int)
            and isinstance(end_hour, int)
            and start_hour <= occurred_at.hour < end_hour
        ):
            return {
                "passed": True,
                "decision": "continue",
                "reason": "request is within active policy time window",
                "window": window.get("name"),
            }

    return {
        "passed": False,
        "decision": "reject",
        "reason": "request is outside active policy time window",
    }


def _evaluate_revenue_floor(
    session: Session,
    rule: PolicyRule,
    request: PolicyEvaluationRequest,
) -> dict[str, Any]:
    floor = _decimal_from_config(rule.configuration.get("amount"))
    if floor is None:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "revenue floor rule is missing a valid amount",
        }

    revenue_wallet = _wallet_by_type_and_currency(
        session,
        wallet_type="revenue",
        currency=request.currency,
    )
    if revenue_wallet is None:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "missing revenue wallet for revenue floor policy",
        }

    if revenue_wallet.balance < floor:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "revenue wallet is below required floor",
            "balance": str(revenue_wallet.balance),
            "floor": str(floor),
        }

    return {
        "passed": True,
        "decision": "continue",
        "reason": "revenue wallet satisfies required floor",
        "balance": str(revenue_wallet.balance),
        "floor": str(floor),
    }


def _evaluate_reserve_minimum(
    rule: PolicyRule,
    request: PolicyEvaluationRequest,
    source_wallet: Wallet,
) -> dict[str, Any]:
    minimum = _decimal_from_config(rule.configuration.get("amount"))
    if minimum is None:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "reserve minimum rule is missing a valid amount",
        }

    projected_balance = source_wallet.balance - request.amount
    if source_wallet.balance < minimum or projected_balance < minimum:
        return {
            "passed": False,
            "decision": "reject",
            "reason": "operating wallet minimum would be violated",
            "balance": str(source_wallet.balance),
            "requested_amount": str(request.amount),
            "projected_balance": str(projected_balance),
            "minimum": str(minimum),
        }

    return {
        "passed": True,
        "decision": "continue",
        "reason": "operating wallet remains above required minimum",
        "balance": str(source_wallet.balance),
        "projected_balance": str(projected_balance),
        "minimum": str(minimum),
    }


def _decimal_from_config(value: Any) -> Decimal | None:
    try:
        if value is None:
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


__all__ = [
    "PolicyEvaluationRequest",
    "create_policy_rule",
    "evaluate_policy",
    "list_policy_rules",
]
