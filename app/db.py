"""
Handles loading the ticket CSV into a local SQLite database
and gives other modules a way to run SQL against it.
"""
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "tickets.db"
CSV_PATH = Path(__file__).parent.parent / "data" / "support_tickets.csv"
TABLE_NAME = "tickets"


def build_database():
    """Reads the CSV and writes it into a fresh SQLite database.
    Safe to call every time the app starts (keeps data in sync with the CSV)."""
    df = pd.read_csv(CSV_PATH)

    # Basic type cleanup so SQL comparisons/math work correctly
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["response_time_hrs"] = pd.to_numeric(df["response_time_hrs"], errors="coerce")
    df["resolution_time_hrs"] = pd.to_numeric(df["resolution_time_hrs"], errors="coerce")
    df["customer_rating"] = pd.to_numeric(df["customer_rating"], errors="coerce")

    conn = sqlite3.connect(DB_PATH)
    df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
    conn.close()
    return len(df)


def get_connection():
    """Returns a live SQLite connection for running queries."""
    return sqlite3.connect(DB_PATH)


def run_sql(query: str):
    """Runs a SQL query and returns rows as a list of dicts.
    Read-only by convention — we never expect INSERT/UPDATE/DELETE here."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
        return rows
    finally:
        conn.close()


def get_reference_now() -> str:
    """
    Returns the latest 'created_at' timestamp in the dataset, as a string.

    This dataset is a static historical snapshot (Jan-Mar 2024), so the
    real wall-clock date is meaningless for questions like "this week" or
    "today". Every module (anomalies, LLM prompts) uses THIS as "now" so
    relative-time questions are answered consistently against the data,
    not against whatever day it happens to be when the app is run.
    """
    rows = run_sql("SELECT MAX(created_at) as max_date FROM tickets")
    return rows[0]["max_date"]


def get_schema_description() -> str:
    """Returns a plain-text schema description for the LLM prompt —
    this is what lets the LLM write SQL WITHOUT ever seeing the actual data rows."""
    return """
Table: tickets
Columns:
- ticket_id (TEXT) - unique ticket ID, e.g. 'TKT-001'
- created_at (DATETIME) - when the ticket was created
- category (TEXT) - one of 'Billing', 'Technical', 'General'
- priority (TEXT) - one of 'Low', 'Medium', 'High', 'Critical'
- status (TEXT) - one of 'Open', 'Resolved', 'Escalated'
- response_time_hrs (REAL) - hours from creation to first response
- resolution_time_hrs (REAL) - hours from creation to resolution (NULL if unresolved)
- agent_id (TEXT) - support agent identifier, e.g. 'AGT-03'
- customer_rating (INTEGER 1-5) - satisfaction rating (NULL if unresolved)
- issue_summary (TEXT) - free-text description of the issue
"""


if __name__ == "__main__":
    count = build_database()
    print(f"Loaded {count} rows into {DB_PATH}")