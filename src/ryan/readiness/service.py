from __future__ import annotations

from dataclasses import dataclass

from ryan.config import Settings


@dataclass(frozen=True)
class ProductionReadinessResult:
    ready: bool
    blockers: list[str]
    decisions: dict[str, str]


def check_production_readiness(settings: Settings) -> ProductionReadinessResult:
    blockers: list[str] = []
    if settings.environment != "production":
        blockers.append("environment must be production")
    if settings.database_url.startswith("sqlite"):
        blockers.append("database_url must use a production transactional database")
    if settings.payment_rail != "stripe":
        blockers.append("payment_rail must be stripe")
    if settings.secret_backend != "aws_secrets_manager":
        blockers.append("secret_backend must be aws_secrets_manager")
    if settings.hosting_environment not in {"container", "aws_ecs"}:
        blockers.append("hosting_environment must be container or aws_ecs")
    if not settings.operator_api_key or not settings.agent_api_key:
        blockers.append("operator and agent API keys must be configured")
    if (
        not settings.stripe_api_key
        or not settings.stripe_webhook_secret
        or not settings.stripe_success_url
        or not settings.stripe_cancel_url
    ):
        blockers.append("Stripe API key, webhook secret, success URL, and cancel URL must be configured")
    if settings.outbound_payment_rail == "simulated":
        blockers.append("outbound_payment_rail must be a configured production rail")
    if not settings.outbound_payment_provider:
        blockers.append("outbound_payment_provider must be configured")
    if not settings.treasury_account_reference:
        blockers.append("treasury_account_reference must be configured")
    if not settings.outbound_live_validation_approved:
        blockers.append("outbound live validation must be operator-approved")
    if not settings.business_model.production_ready:
        blockers.append("business model must be marked production_ready")

    return ProductionReadinessResult(
        ready=not blockers,
        blockers=blockers,
        decisions={
            "payment_rail": settings.payment_rail,
            "outbound_payment_rail": settings.outbound_payment_rail,
            "outbound_payment_provider": settings.outbound_payment_provider or "unconfigured",
            "secret_backend": settings.secret_backend,
            "hosting_environment": settings.hosting_environment,
            "database": "external" if not settings.database_url.startswith("sqlite") else "sqlite",
        },
    )


__all__ = ["ProductionReadinessResult", "check_production_readiness"]
