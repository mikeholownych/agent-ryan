from importlib import import_module
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_app_factory_returns_fastapi_health_endpoint():
    from ryan.app import create_app

    app = create_app()

    assert isinstance(app, FastAPI)
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ryan"}


def test_settings_load_sandbox_defaults(monkeypatch):
    monkeypatch.delenv("RYAN_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RYAN_DATABASE_URL", raising=False)

    from ryan.config import Settings

    settings = Settings()

    assert settings.environment == "sandbox"
    assert settings.database_url == "sqlite:///./ryan.sqlite3"


def test_required_module_layout_imports_cleanly():
    modules = [
        "ryan",
        "ryan.app",
        "ryan.config",
        "ryan.db",
        "ryan.agent",
        "ryan.console",
        "ryan.ledger",
        "ryan.payments",
        "ryan.policy",
        "ryan.telemetry",
        "ryan.wallets",
    ]

    for module in modules:
        import_module(module)


def test_migration_scaffold_exists():
    assert Path("alembic.ini").is_file()
    assert Path("migrations/env.py").is_file()
    assert Path("migrations/versions").is_dir()
