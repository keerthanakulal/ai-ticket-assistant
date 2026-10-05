"""
Streamlit UI - a thin front-end that calls the FastAPI backend.
No business logic here on purpose: the API is the single source of
truth, and this file only handles displaying it.

Run the API first (uvicorn app.main:app), then run this with:
    streamlit run streamlit_app.py
"""
import streamlit as st
import requests
import pandas as pd

API_URL = "http://127.0.0.1:8000"

def show_chart(rows):
    """Draws a bar or line chart when the result is a small table:
    first column = labels (text or dates), other columns = numbers."""
    if not rows or not (2 <= len(rows) <= 30):
        return
    df = pd.DataFrame(rows)
    label, values = df.columns[0], list(df.columns[1:])
    if not values or pd.api.types.is_numeric_dtype(df[label]):
        return
    if not all(pd.api.types.is_numeric_dtype(df[c]) for c in values):
        return
    if df[label].nunique() != len(df):
        return

    parsed = pd.to_datetime(df[label], errors="coerce", format="mixed")
    if parsed.notna().all():
        # Labels are dates (e.g. months) -> line chart, sorted by date
        st.line_chart(df.assign(**{label: parsed}).set_index(label).sort_index())
    else:
        st.bar_chart(df.set_index(label))

st.set_page_config(page_title="AI Ticket Assistant", layout="wide")
st.title("AI data assistant")

# ---- Sidebar: upload your own CSV ----
with st.sidebar:
    st.header("Dataset")
    if "uploader_key" not in st.session_state:
        st.session_state.uploader_key = 0

    uploaded = st.file_uploader(
        "Upload a CSV file", type=["csv"],
        key=f"uploader_{st.session_state.uploader_key}",
    )

    if uploaded is not None and st.session_state.get("loaded_file") != uploaded.name:
        try:
            r = requests.post(
                f"{API_URL}/upload",
                files={"file": (uploaded.name, uploaded.getvalue(), "text/csv")},
                timeout=60,
            )
            if r.status_code == 200:
                st.session_state.loaded_file = uploaded.name
                st.session_state.chat_history = []
                st.success(f"Loaded {r.json()['rows']} rows from {uploaded.name}")
            else:
                st.error(r.json().get("detail", "Upload failed"))
        except requests.exceptions.ConnectionError:
            st.error("Could not reach the API.")

    if st.button("Reset to tickets data"):
        requests.post(f"{API_URL}/reset", timeout=30)
        st.session_state.loaded_file = None
        st.session_state.chat_history = []
        st.session_state.uploader_key += 1
        st.rerun()

# ---- Is the current data the support-ticket data? ----
try:
    is_tickets = requests.get(f"{API_URL}/dataset", timeout=10).json()["is_ticket_dataset"]
except requests.exceptions.ConnectionError:
    is_tickets = True

if is_tickets:
    tab1, tab2 = st.tabs(["Ask a question", "Anomalies"])
else:
    (tab1,) = st.tabs(["Ask a question"])
    tab2 = None

with tab1:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # 1. Draw ALL past turns first, in order, oldest to newest.
    for turn in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            st.write(turn["answer"])
            if turn.get("sql"):
                with st.expander("Show generated SQL"):
                    st.code(turn["sql"], language="sql")
            if turn.get("rows"):
                show_chart(turn["rows"])
                st.caption(f"Full result: {turn['row_count']} row(s)")
                st.dataframe(turn["rows"], use_container_width=True)

    if st.session_state.chat_history:
        if st.button("Clear conversation"):
            st.session_state.chat_history = []
            st.rerun()

    # 2. Chat input goes LAST in the code, so it's the last thing on the
    #    page - visually at the bottom, below every message, every time.
    question = st.chat_input("Ask a question about the tickets...")
    if question:
        with st.spinner("Thinking..."):
            try:
                history = [
                    {"question": t["question"], "sql": t.get("sql")}
                    for t in st.session_state.chat_history[-3:]
                ]
                response = requests.post(
                    f"{API_URL}/query",
                    json={"question": question, "history": history},
                    timeout=30,
                )
                if response.status_code == 200:
                    data = response.json()
                    st.session_state.chat_history.append({
                        "question": question,
                        "answer": data["answer"],
                        "sql": data.get("sql"),
                        "rows": data.get("rows"),
                        "row_count": data.get("row_count"),
                    })
                else:
                    detail = response.json().get("detail")
                    st.session_state.chat_history.append({
                        "question": question,
                        "answer": f"API error ({response.status_code}): {detail}",
                        "sql": None, "rows": None,
                    })
            except requests.exceptions.ConnectionError:
                st.session_state.chat_history.append({
                    "question": question,
                    "answer": "Could not reach the API. Make sure it's running: uvicorn app.main:app",
                    "sql": None, "rows": None,
                })
        # Re-run so the loop above (step 1) picks up and displays this new
        # turn in its proper place - never rendered separately/inline here.
        st.rerun()

if tab2 is not None:
    with tab2:
        st.subheader("Flagged anomalies")
        if st.button("Refresh anomalies"):
            st.rerun()
        try:
            response = requests.get(f"{API_URL}/anomalies", timeout=30)
            if response.status_code == 200:
                data = response.json()
                st.metric("Total anomalies found", data["count"])
                st.dataframe(data["anomalies"], use_container_width=True)
            else:
                st.error(f"API error ({response.status_code})")
        except requests.exceptions.ConnectionError:
            st.error("Could not reach the API. Make sure it's running: uvicorn app.main:app")