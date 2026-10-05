"""
FastAPI backend - exposes the system as 3 REST endpoints:
  GET  /health    - health check
  POST /query     - natural language question -> answer
  GET  /anomalies - rule-based anomaly report

Rebuilds the SQLite database from the CSV once, at startup, so the
API always reflects the current CSV file without a separate manual step.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from app.db import build_database
from app.llm import answer_question
from app.anomalies import get_all_anomalies
import io
import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File
from app.db import build_database, load_dataframe, is_ticket_dataset

app = FastAPI(title="AI Ticket Assistant", version="1.0")


@app.on_event("startup")
def startup():
    build_database()


class QueryRequest(BaseModel):
    question: str
    history: list = []

@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/query")
def query(request: QueryRequest):
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="'question' must not be empty")
    try:
        result = answer_question(request.question, request.history)
    except ValueError as e:
        # Raised when the LLM's SQL fails our safety check or comes back empty
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    return {
        "question": result["question"],
        "sql": result["sql"],
        "answer": result["answer"],
        "row_count": len(result["rows"]),
        "rows": result["rows"],
    }


@app.get("/anomalies")
def anomalies():
    try:
        results = get_all_anomalies()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    return {"count": len(results), "anomalies": results}

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file")
    try:
        df = pd.read_csv(io.BytesIO(await file.read()))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read CSV: {e}")
    if df.empty or len(df.columns) == 0:
        raise HTTPException(status_code=400, detail="The CSV is empty")
    rows = load_dataframe(df)
    return {"rows": rows, "columns": list(df.columns),
            "is_ticket_dataset": is_ticket_dataset()}


@app.post("/reset")
def reset():
    rows = build_database()
    return {"rows": rows, "is_ticket_dataset": True}


@app.get("/dataset")
def dataset():
    return {"is_ticket_dataset": is_ticket_dataset()}