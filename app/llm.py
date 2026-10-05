"""
Handles all Groq LLM calls.

Two paths, chosen by a simple keyword check (is_anomaly_question):

1. Anomaly questions ("any anomalies?", "unusual resolution times?")
   -> handled by app/anomalies.py rules, NOT the LLM writing SQL.
   Anomaly detection is a statistical concept (mean + 2*std, etc.) that
   SQL/an LLM can't reliably reconstruct on demand - so we run the same
   trusted rules from Step 3. If the question also has a time phrase
   ("this week", "today"), we filter the list IN CODE (exact date math)
   before handing it to the LLM - the LLM only writes the sentence, it
   never has to do date arithmetic itself, which it's unreliable at.
   (Only used for the support-ticket dataset.)

2. Everything else -> the standard NL-to-SQL pipeline:
   a. question_to_sql()  - LLM sees only the schema + question, writes SQL
   b. format_answer()    - LLM sees only the question + query RESULT, writes a sentence

The LLM never sees the raw rows in step (a) - only the schema.
This keeps the design safe (LLM can't hallucinate raw data into its
reasoning) and scalable (works the same whether the table has 500 rows
or 5 million).
"""
import os
import re
import sqlite3
from datetime import timedelta
import pandas as pd
from groq import Groq
from dotenv import load_dotenv
from app.db import get_schema_description, run_readonly_sql, get_reference_now, is_ticket_dataset
from app.anomalies import get_all_anomalies

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "openai/gpt-oss-120b"

ANOMALY_KEYWORDS = ["anomaly", "anomalies", "unusual", "outlier", "outliers", "abnormal", "flagged"]


def is_anomaly_question(question: str) -> bool:
    """Cheap keyword check - no LLM call needed to decide the route."""
    q = question.lower()
    return any(word in q for word in ANOMALY_KEYWORDS)


def _extract_sql(text: str) -> str:
    """LLMs often wrap SQL in ```sql ... ``` even when told not to. Strip it if present."""
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip().rstrip(";")


FORBIDDEN_WORDS = {"insert", "update", "delete", "drop", "alter", "attach",
                   "detach", "pragma", "create", "replace", "vacuum"}


def _is_safe_select(sql: str) -> bool:
    """
    Guardrail: only allow a single read-only SELECT (or WITH ... SELECT).
    Forbidden words are matched as WHOLE WORDS, outside of quoted text,
    so a value like 'password update' in a filter is not blocked.
    """
    # Remove quoted text first ('...' and "...") so words inside values are ignored
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "", sql)
    normalized = stripped.strip().lower()

    if not normalized.startswith(("select", "with")):
        return False
    if ";" in normalized or "--" in normalized or "/*" in normalized:
        return False
    words = set(re.findall(r"[a-z_]+", normalized))
    return not (words & FORBIDDEN_WORDS)


def question_to_sql(question: str, previous_sql: str = "", error: str = "", history=None) -> str:
    """Turn a natural language question into a SQL query."""
    schema = get_schema_description()
    reference_now = get_reference_now()
    time_note = (
        f'IMPORTANT: This is a static historical dataset. Treat {reference_now} '
        f'as the current date/time ("now") for relative phrases like "today", '
        f'"this week", "this month". Do NOT use the real current date.'
        if reference_now else ""
    )
    retry_note = (
        f"\nYour previous query failed.\nPrevious SQL: {previous_sql}\n"
        f"SQLite error: {error}\nFix the query and return only the corrected SQL.\n"
        if error else ""
    )
    history_note = ""
    if history:
        lines = [
            f"- Q: {t['question']}\n  SQL: {t['sql']}"
            for t in history[-3:] if t.get("sql")
        ]
        if lines:
            history_note = (
                "Earlier in this conversation (use it ONLY if the new question is a "
                "follow-up that refers back to it, otherwise ignore it):\n"
                + "\n".join(lines) + "\n"
            )
    prompt = f"""You are a SQLite expert. Given this table schema:
{schema}

{time_note}
Use SQLite date functions (julianday, datetime, strftime) as needed.

Write exactly ONE SQLite SELECT query that answers the question below.
Rules:
- Return ONLY the raw SQL. No markdown, no explanation, no semicolon.
- Only use SELECT. Never modify data.
- Use the exact column and table names from the schema.
- Include any column values needed to fully answer the question (not just IDs).

{history_note}
{retry_note}
Question: {question}
SQL:"""
    
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=800,
        reasoning_effort="low",
    )
    sql = _extract_sql(response.choices[0].message.content)

    if not sql:
        raise ValueError(
            f"LLM returned empty SQL (finish_reason={response.choices[0].finish_reason}). "
            "This usually means it ran out of tokens on internal reasoning - try raising max_tokens."
        )

    if not _is_safe_select(sql):
        raise ValueError(f"Generated SQL failed the safety check: {sql}")
    return sql


def format_answer(question: str, rows: list, extra_context: str = "") -> str:
    """Turn a list of result rows (from SQL or from anomaly rules) into a sentence."""
    if not rows:
        return "No matching data was found for that question."

    total_count = len(rows)
    # Cap what we send the LLM - it only needs enough rows to summarize, not all of them
    sample = rows[:30]
    shown_note = (
        f"(Only the first {len(sample)} of {total_count} rows are shown below - "
        f"the true total is {total_count}, always use that number, not the count you can see.)"
        if total_count > len(sample) else ""
    )
    prompt = f"""Question: {question}
{extra_context}
TOTAL MATCHING ROWS: {total_count}
{shown_note}
Row data: {sample}

Answer the question in clear natural language using ONLY this data.
The correct total to report is {total_count} - use that exact number, do not count the rows in "Row data" yourself.
Do not invent numbers or details that aren't in the data.
Do not do any date math yourself - the data has already been filtered correctly for you.
Do not format your answer as a table or list of every row - write a short
summary sentence or two. The full data table is shown separately to the user.
Be precise: only describe what's true of THIS result set, never make a
sweeping claim about "the whole dataset" (e.g. never say "all tickets
are marked X" - say "all N matching tickets are marked X")."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=600,
        reasoning_effort="low",
    )
    return response.choices[0].message.content.strip()


def _filter_anomalies_by_time(anomalies: list, question: str) -> tuple[list, str]:
    """
    If the question mentions a relative time window, filter the anomaly
    list to that window using exact date math (pandas), not the LLM.
    Returns (filtered_list, note_for_the_llm_prompt).
    """
    q = question.lower()
    reference_now = pd.to_datetime(get_reference_now())

    if "today" in q:
        cutoff, label = reference_now - timedelta(days=1), "the last 24 hours"
    elif "this week" in q:
        cutoff, label = reference_now - timedelta(days=7), "the last 7 days"
    elif "this month" in q:
        cutoff, label = reference_now - timedelta(days=30), "the last 30 days"
    else:
        return anomalies, ""

    filtered = [a for a in anomalies if pd.to_datetime(a["created_at"]) >= cutoff]
    note = (
        f"(Already filtered to {label}, i.e. tickets created on/after {cutoff.isoformat()}, "
        f"relative to the dataset's latest date {reference_now.isoformat()}.)"
    )
    return filtered, note


def answer_anomaly_question(question: str) -> dict:
    """Runs the trusted rule-based anomaly checks, filters by time if asked, then summarizes."""
    all_anomalies = get_all_anomalies()
    filtered, note = _filter_anomalies_by_time(all_anomalies, question)
    answer = format_answer(question, filtered, extra_context=note)
    return {"question": question, "sql": None, "rows": filtered, "answer": answer}


def answer_question(question: str, history=None) -> dict:
    """Routes the question, then runs the appropriate pipeline."""
    # Anomaly rules only exist for the support-ticket dataset
    if is_anomaly_question(question) and is_ticket_dataset():
        return answer_anomaly_question(question)

    sql = question_to_sql(question, history=history)
    try:
        rows = run_readonly_sql(sql)
    except sqlite3.Error as e:
        # One retry: tell the LLM what went wrong and let it fix the query
        sql = question_to_sql(question, previous_sql=sql, error=str(e), history=history)
        rows = run_readonly_sql(sql)
    answer = format_answer(question, rows)
    return {"question": question, "sql": sql, "rows": rows, "answer": answer}


if __name__ == "__main__":
    print("Ask a question about your data (type 'exit' to quit)")
    while True:
        question = input("\nYour question: ").strip()
        if question.lower() in ("exit", "quit"):
            break
        if not question:
            continue
        result = answer_question(question)
        print("SQL:", result["sql"])
        print("Answer:", result["answer"])