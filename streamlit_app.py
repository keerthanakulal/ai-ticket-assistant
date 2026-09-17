"""
Streamlit UI - a thin front-end that calls the FastAPI backend.
No business logic here on purpose: the API is the single source of
truth, and this file only handles displaying it.

Run the API first (uvicorn app.main:app), then run this with:
    streamlit run streamlit_app.py
"""
import streamlit as st
import requests

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="AI Ticket Assistant", layout="wide")
st.title("AI support ticket assistant")

tab1, tab2 = st.tabs(["Ask a question", "Anomalies"])

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
                response = requests.post(f"{API_URL}/query", json={"question": question}, timeout=30)
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