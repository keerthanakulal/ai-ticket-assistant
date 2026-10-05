"""
Loads a CSV into SQLite and gives other modules a way to query it.
Works with ANY csv: the schema description is built from the real columns.
"""
import re
import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "tickets.db"
CSV_PATH = Path(__file__).parent.parent / "data" / "support_tickets.csv"
TABLE_NAME = "data"

TICKET_COLUMNS = {"ticket_id", "created_at", "category", "priority",
                  "status", "resolution_time_hrs", "agent_id"}


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Make column names safe for SQL: "Order Date" -> "order_date"
    df.columns = [
        re.sub(r"\W+", "_", str(c).strip()).strip("_").lower() or f"col_{i}"
        for i, c in enumerate(df.columns)
    ]
    # Convert date-looking text columns to real datetimes
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]) and (
            col.endswith("_at") or "date" in col or "time" in col
        ):
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().mean() > 0.8:
                df[col] = parsed
    return df


def load_dataframe(df: pd.DataFrame) -> int:
    """Writes a dataframe into SQLite, replacing the current dataset."""
    df = _clean_dataframe(df)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
    conn.close()
    return len(df)


def build_database() -> int:
    """Loads the default tickets CSV (used at API startup)."""
    return load_dataframe(pd.read_csv(CSV_PATH))


def get_connection():
    return sqlite3.connect(DB_PATH)


def run_sql(query: str):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query).fetchall()]
    finally:
        conn.close()

def run_readonly_sql(query: str):
    """Runs AI-written SQL on a READ-ONLY connection.
    SQLite itself refuses any write, even if the safety check misses one."""
    conn = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query).fetchall()]
    finally:
        conn.close()


def get_columns() -> list:
    """Returns [(name, sqlite_type), ...] for the current dataset."""
    conn = get_connection()
    try:
        return [(r[1], r[2]) for r in conn.execute(f"PRAGMA table_info({TABLE_NAME})")]
    finally:
        conn.close()


def is_ticket_dataset() -> bool:
    """True only if the loaded data has the support-ticket columns.
    The anomaly rules only make sense for that data."""
    return TICKET_COLUMNS.issubset({name for name, _ in get_columns()})


def get_reference_now():
    """Latest timestamp in the first date column, used as 'now'.
    Returns None if the dataset has no date column."""
    for name, col_type in get_columns():
        if col_type.upper() in ("TIMESTAMP", "DATETIME", "DATE"):
            return run_sql(f"SELECT MAX({name}) AS m FROM {TABLE_NAME}")[0]["m"]
    return None


def get_schema_description() -> str:
    """Builds the schema text for the LLM from the real columns.
    For text columns with few distinct values (<=10), it lists them
    so the LLM uses exact values (e.g. 'Open', not 'open')."""
    lines = [f"Table: {TABLE_NAME}", "Columns:"]
    for name, col_type in get_columns():
        line = f"- {name} ({col_type or 'TEXT'})"
        if (col_type or "TEXT").upper() == "TEXT":
            vals = run_sql(
                f"SELECT DISTINCT {name} AS v FROM {TABLE_NAME} "
                f"WHERE {name} IS NOT NULL LIMIT 11"
            )
            if 0 < len(vals) <= 10:
                line += " - one of: " + ", ".join(f"'{v['v']}'" for v in vals)
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"Loaded {build_database()} rows into {DB_PATH}")
    print(get_schema_description())