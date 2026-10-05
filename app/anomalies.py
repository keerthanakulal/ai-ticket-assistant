"""
Rule-based anomaly detection. No LLM here on purpose:
these are simple statistical/threshold checks, and doing them
in plain Python/SQL is faster, cheaper, and more reliable
than asking an LLM to "notice" outliers.
"""
from datetime import timedelta
import pandas as pd
from app.db import get_connection, get_reference_now, is_ticket_dataset


def find_long_resolution_anomalies():
    """
    Flags resolved tickets whose resolution_time_hrs is unusually high
    COMPARED TO OTHER TICKETS IN THE SAME CATEGORY.
    Threshold: mean + 2 standard deviations (per category).
    Using per-category stats because 'Technical' issues naturally take
    longer than 'Billing' issues - a single global threshold would be unfair.
    """
    conn = get_connection()
    df = pd.read_sql(
        "SELECT * FROM data WHERE status = 'Resolved' AND resolution_time_hrs IS NOT NULL",
        conn,
    )
    conn.close()
    df["created_at"] = pd.to_datetime(df["created_at"])

    anomalies = []
    for category, group in df.groupby("category"):
        mean = group["resolution_time_hrs"].mean()
        std = group["resolution_time_hrs"].std()
        threshold = mean + 2 * std
        flagged = group[group["resolution_time_hrs"] > threshold]
        for _, row in flagged.iterrows():
            anomalies.append({
                "ticket_id": row["ticket_id"],
                "reason": "long_resolution_time",
                "detail": f"Resolution took {row['resolution_time_hrs']:.1f}h, "
                          f"vs category average {mean:.1f}h (threshold {threshold:.1f}h)",
                "category": category,
                "priority": row["priority"],
                "agent_id": row["agent_id"],
                "created_at": row["created_at"].isoformat(),
            })
    return anomalies


def find_unresolved_high_priority():
    """
    Flags tickets that are:
    - still open (status is 'Open' or 'Escalated', not 'Resolved')
    - High or Critical priority
    - created more than 24 hours before the most recent activity in the dataset

    NOTE: we use the latest timestamp IN THE DATA as "now" (via
    db.get_reference_now()), not the real current date. This is a static
    historical dataset (Jan-Mar 2024), so comparing against the real
    wall-clock date would flag almost every unresolved ticket trivially.
    In a live system, you'd swap this for datetime.now().
    """
    conn = get_connection()
    df = pd.read_sql(
        "SELECT * FROM data WHERE status != 'Resolved' AND priority IN ('High', 'Critical')",
        conn,
    )
    conn.close()

    df["created_at"] = pd.to_datetime(df["created_at"])
    reference_now = pd.to_datetime(get_reference_now())
    cutoff = reference_now - timedelta(hours=24)

    anomalies = []
    for _, row in df[df["created_at"] < cutoff].iterrows():
        age_hrs = (reference_now - row["created_at"]).total_seconds() / 3600
        anomalies.append({
            "ticket_id": row["ticket_id"],
            "reason": "unresolved_high_priority",
            "detail": f"{row['priority']} priority, still {row['status']} after {age_hrs:.0f}h",
            "category": row["category"],
            "priority": row["priority"],
            "agent_id": row["agent_id"],
            "created_at": row["created_at"].isoformat(),
        })
    return anomalies


def get_all_anomalies():
    """Combines both anomaly checks. Returns [] for non-ticket datasets."""
    if not is_ticket_dataset():
        return []
    return find_long_resolution_anomalies() + find_unresolved_high_priority()

if __name__ == "__main__":
    results = get_all_anomalies()
    print(f"Found {len(results)} anomalies")
    for a in results[:5]:
        print(a)