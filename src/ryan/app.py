from fastapi import FastAPI

from ryan.config import Settings, get_settings
from ryan.operator.router import router as operator_router
from ryan.payments.router import router as payment_router
from ryan.policy.router import router as policy_router
from ryan.reports.router import router as report_router
from ryan.wallets.router import router as wallet_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title="Ryan", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": resolved_settings.service_name}

    app.include_router(policy_router)
    app.include_router(wallet_router)
    app.include_router(payment_router)
    app.include_router(report_router)
    app.include_router(operator_router)

    return app


app = create_app()

__all__ = ["app", "create_app"]
