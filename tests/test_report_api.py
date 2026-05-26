from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from ryan.app import create_app
from ryan.db import Base, create_database_engine, get_session
from ryan.models import Payment, Wallet


def _client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'report-api.sqlite3'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    app = create_app()

    def override_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), Session()


def test_daily_report_api_generates_and_returns_report(tmp_path):
    client, session = _client_with_session(tmp_path)
    session.add_all(
        [
            Wallet(
                type="revenue",
                balance=Decimal("100.00"),
                currency="USD",
                locked=False,
                limits={},
            ),
            Wallet(
                type="operating",
                balance=Decimal("50.00"),
                currency="USD",
                locked=False,
                limits={},
            ),
            Wallet(
                type="reserve",
                balance=Decimal("25.00"),
                currency="USD",
                locked=False,
                limits={},
            ),
            Payment(
                amount=Decimal("100.00"),
                currency="USD",
                status="settled",
                source="customer",
                payment_provider="simulated",
                provider_reference="provider-event-001",
                settlement_time=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
            ),
        ]
    )
    session.commit()

    response = client.get(
        "/api/reports/daily",
        params={"date": "2026-05-25", "actor": "operator:test"},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "daily"
    assert response.json()["status"] == "generated"
    assert response.json()["summary"]["revenue_total"] == "100.00"
    assert response.json()["summary"]["wallet_balances"]["operating"] == "50.00"
    session.close()
