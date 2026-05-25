from fastapi import FastAPI

from ryan.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(title="Ryan", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": resolved_settings.service_name}

    return app


app = create_app()

__all__ = ["app", "create_app"]
