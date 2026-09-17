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

app = FastAPI(title="AI Ticket Assistant", version="1.0")


@app.on_event("startup")
def startup():
    build_database()


class QueryRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/query")
def query(request: QueryRequest):
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="'question' must not be empty")
    try:
        result = answer_question(request.question)
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