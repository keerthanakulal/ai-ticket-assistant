import pandas as pd
import pytest
from app import db
from app.anomalies import get_all_anomalies, find_unresolved_high_priority


@pytest.fixture(autouse=True)
def tickets_db(tmp_path, monkeypatch):
    """Use a small temporary database so tests never touch your real data."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    rows = []
    # 20 normal Billing tickets: resolved in 10-14 hours
    for i in range(20):
        rows.append(dict(ticket_id=f"B-{i}", created_at="2024-01-01 10:00",
                         category="Billing", priority="Low", status="Resolved",
                         response_time_hrs=1.0, resolution_time_hrs=10 + i % 5,
                         agent_id="AGT-01", customer_rating=4.0, issue_summary="x"))
    # 1 extreme outlier
    rows.append(dict(ticket_id="OUTLIER", created_at="2024-01-02 10:00",
                     category="Billing", priority="Low", status="Resolved",
                     response_time_hrs=1.0, resolution_time_hrs=200.0,
                     agent_id="AGT-01", customer_rating=2.0, issue_summary="x"))
    # Critical ticket still open and old (newest ticket below sets "now")
    rows.append(dict(ticket_id="OLD-OPEN", created_at="2024-01-03 10:00",
                     category="Technical", priority="Critical", status="Open",
                     response_time_hrs=1.0, resolution_time_hrs=None,
                     agent_id="AGT-02", customer_rating=None, issue_summary="x"))
    # Low priority open ticket - must NOT be flagged
    rows.append(dict(ticket_id="OLD-LOW", created_at="2024-01-03 10:00",
                     category="General", priority="Low", status="Open",
                     response_time_hrs=1.0, resolution_time_hrs=None,
                     agent_id="AGT-02", customer_rating=None, issue_summary="x"))
    # Newest ticket: sets the reference "now" to 2024-01-10
    rows.append(dict(ticket_id="NEWEST", created_at="2024-01-10 10:00",
                     category="General", priority="Low", status="Resolved",
                     response_time_hrs=1.0, resolution_time_hrs=5.0,
                     agent_id="AGT-03", customer_rating=5.0, issue_summary="x"))
    db.load_dataframe(pd.DataFrame(rows))


def test_flags_long_resolution_outlier():
    ids = [a["ticket_id"] for a in get_all_anomalies()
           if a["reason"] == "long_resolution_time"]
    assert ids == ["OUTLIER"]


def test_flags_old_open_critical_ticket():
    ids = [a["ticket_id"] for a in find_unresolved_high_priority()]
    assert "OLD-OPEN" in ids


def test_does_not_flag_low_priority_open_ticket():
    ids = [a["ticket_id"] for a in find_unresolved_high_priority()]
    assert "OLD-LOW" not in ids


def test_no_anomalies_for_non_ticket_data():
    db.load_dataframe(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))
    assert get_all_anomalies() == []