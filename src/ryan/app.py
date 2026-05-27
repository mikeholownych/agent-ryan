from hmac import compare_digest

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import JSONResponse

from ryan.agent.router import router as agent_router
from ryan.config import Settings, get_settings
from ryan.operator.router import router as operator_router
from ryan.payments.router import router as payment_router
from ryan.policy.router import router as policy_router
from ryan.readiness.router import router as readiness_router
from ryan.reports.router import router as report_router
from ryan.wallets.router import router as wallet_router


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title="Ryan", version="0.1.0")
    app.dependency_overrides[get_settings] = lambda: resolved_settings

    @app.middleware("http")
    async def production_auth_middleware(request: Request, call_next):
        if resolved_settings.environment != "production":
            return await call_next(request)

        if request.url.path in {"/health", "/api/payments/stripe/webhook"}:
            return await call_next(request)

        role = request.headers.get("X-Ryan-Role", "")
        api_key = request.headers.get("X-Ryan-Api-Key", "")
        if not role or not api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Ryan production API authentication required"},
            )

        if not _role_key_matches(resolved_settings, role=role, api_key=api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid Ryan production API credentials"},
            )

        if not _role_can_access_path(role=role, path=request.url.path):
            return JSONResponse(
                status_code=403,
                content={"detail": "Ryan role is not authorized for this route"},
            )

        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": resolved_settings.service_name}

    app.include_router(policy_router)
    app.include_router(wallet_router)
    app.include_router(payment_router)
    app.include_router(report_router)
    app.include_router(operator_router)
    app.include_router(agent_router)
    app.include_router(readiness_router)

    return app


def _role_key_matches(settings: Settings, *, role: str, api_key: str) -> bool:
    if role == "operator" and settings.operator_api_key is not None:
        return compare_digest(api_key, settings.operator_api_key)
    if role == "agent" and settings.agent_api_key is not None:
        return compare_digest(api_key, settings.agent_api_key)
    return False


def _role_can_access_path(*, role: str, path: str) -> bool:
    if role == "operator":
        return True
    if role == "agent":
        return path in {
            "/api/plan",
            "/api/execute",
            "/api/status",
            "/api/agent/console",
            "/api/payments/create",
        }
    return False


app = create_app()

__all__ = ["app", "create_app"]
