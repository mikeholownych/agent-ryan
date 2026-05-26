from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from ryan.app import create_app
from ryan.db import Base, create_database_engine, get_session
from ryan.models import ExceptionRecord, LedgerEntry, PolicyDecision, Report, Wallet


def _client_with_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'operator-api.sqlite3'}")
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


def _seed_console_state(session):
    wallet = Wallet(
        type="operating",
        balance=Decimal("50.00"),
        currency="USD",
        locked=False,
        limits={"minimum": "5.00"},
    )
    decision = PolicyDecision(
        action_type="expense_execute",
        decision="reject",
        reason="vendor is not allowlisted",
        rule_results={},
        request_reference_type="expense",
        request_reference_id="expense-001",
        actor="agent:ryan",
    )
    exception = ExceptionRecord(
        type="policy_rejection",
        severity="high",
        status="open",
        reason="vendor is not allowlisted",
        reference_type="expense",
        reference_id="expense-001",
    )
    report = Report(
        type="daily",
        period_start=datetime(2026, 5, 25, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 26, 0, 0, tzinfo=UTC),
        status="generated",
        summary={"revenue_total": "100.00", "expense_total": "10.00"},
    )
    event = LedgerEntry(
        type="audit.expense.requested",
        amount=None,
        currency=None,
        reference_type="expense",
        reference_id="expense-001",
        timestamp=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        actor="agent:ryan",
        metadata_={},
    )
    session.add_all([wallet, decision, exception, report, event])
    session.commit()
    return exception


def test_operator_console_api_returns_required_state(tmp_path):
    client, session = _client_with_session(tmp_path)
    _seed_console_state(session)

    response = client.get("/api/operator/console")

    assert response.status_code == 200
    payload = response.json()
    assert payload["wallets"][0]["type"] == "operating"
    assert payload["policy_decisions"][0]["reason"] == "vendor is not allowlisted"
    assert payload["exceptions"][0]["type"] == "policy_rejection"
    assert payload["daily_pnl"]["revenue_total"] == "100.00"
    assert payload["recent_actions"][0]["type"] == "audit.expense.requested"
    assert payload["kill_switch"]["active"] is False
    session.close()


def test_operator_console_kill_switch_controls(tmp_path):
    client, session = _client_with_session(tmp_path)

    activate_response = client.post(
        "/api/operator/kill-switch/activate",
        json={"actor": "operator:test", "reason": "manual stop"},
    )
    deactivate_response = client.post(
        "/api/operator/kill-switch/deactivate",
        json={"actor": "operator:test", "reason": "resume"},
    )

    assert activate_response.status_code == 200
    assert activate_response.json()["active"] is True
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["active"] is False
    session.close()


def test_operator_console_exception_review_control(tmp_path):
    client, session = _client_with_session(tmp_path)
    exception = _seed_console_state(session)

    response = client.post(
        f"/api/operator/exceptions/{exception.id}/status",
        json={
            "status": "resolved",
            "actor": "operator:test",
            "reason": "handled",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    session.close()
