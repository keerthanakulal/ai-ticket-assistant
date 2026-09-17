# AI Support Ticket Assistant

An AI-powered system for querying and monitoring a customer support ticket
dataset in natural language, built for the DOTMappers AI Engineer assessment.

## What it does

- Ingests a 500-row support ticket CSV into a queryable SQLite database
- Answers natural language questions about the tickets (e.g. "Which agent
  has the lowest average customer rating?")
- Detects and flags anomalies: abnormally long resolution times, and
  unresolved High/Critical priority tickets open more than 24 hours
- Exposes everything through a REST API (FastAPI) and a chat-style web
  UI (Streamlit)

## Setup instructions

**Requirements:** Python 3.9+, a free Groq API key.

1. Clone the repo and move into it:
   ```
   git clone <your-repo-url>
   cd ai-ticket-assistant
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Get a free Groq API key at https://console.groq.com (Sign up ->
   API Keys -> Create API Key).

4. Copy `.env.example` to `.env` and paste your key in:
   ```
   cp .env.example .env
   ```
   Then edit `.env` so it looks like:
   ```
   GROQ_API_KEY=your_actual_key_here
   ```

5. Start everything with a single command:
   ```
   python run.py
   ```
   This starts the FastAPI backend on `http://127.0.0.1:8000`, waits for
   it to become healthy, then launches the Streamlit UI (opens
   automatically in your browser). Press Ctrl+C once to stop both.

   Alternatively, the two parts can be run separately if preferred:
   ```
   uvicorn app.main:app --reload
   streamlit run streamlit_app.py
   ```

## Architecture overview

```
support_tickets.csv
        |
        v
   SQLite database  <-------------------+
        |                                |
        v                                |
   FastAPI backend  ------->  Groq LLM (NL question -> SQL)
   (/health, /query,          openai/gpt-oss-120b
    /anomalies)
        |
        v
  Streamlit chat UI  (calls the API, renders answers + full data tables)
```

**Design decisions and why:**

- **SQLite as the data layer.** The CSV is loaded into SQLite on every API
  startup (`app/db.py`), rather than querying the CSV/pandas directly.
  This makes the data genuinely "queryable" via SQL, and scales the same
  way whether the table has 500 rows or 5 million.

- **Two-step LLM pipeline for NL queries**, kept deliberately separate:
  1. `question_to_sql()` - the LLM sees only the table schema (never the
     raw data) and writes one SQL SELECT statement.
  2. The backend executes that SQL itself against SQLite - the real
     answer comes from the database, not the LLM's memory.
  3. `format_answer()` - the LLM sees the actual query result and writes
     a short natural-language sentence.

  This means the LLM's job is strictly "understand the question, write a
  query, describe the result" - it never gets a chance to invent a
  number. This was a specific requirement in the assessment brief, and
  the architecture enforces it structurally rather than just hoping the
  LLM behaves.

- **Anomaly detection is NOT done by the LLM.** Both anomaly rules
  (`app/anomalies.py`) are plain Python/pandas: a per-category
  mean + 2*std threshold for long resolution times, and a simple
  status/priority/age filter for unresolved high-priority tickets.
  Statistical thresholds are something code can compute exactly and an
  LLM can't reliably reconstruct on demand - so anomaly questions are
  routed (via a keyword check) to these trusted rules instead of the
  NL-to-SQL path, and the LLM's only job there is to summarize the
  (already correct) result.

- **A single reference "now" for the whole dataset.** This is a static
  historical dataset (Jan-Mar 2024), so comparing against the real
  wall-clock date would make every relative-time question ("this week",
  "unresolved for 24 hours") behave nonsensically. `db.get_reference_now()`
  returns the latest `created_at` timestamp in the data, and every module
  (anomaly rules, LLM prompts) treats that as "now" instead of the real
  current date.

- **A safety guardrail on generated SQL.** Before any LLM-written SQL is
  executed, it's checked to (a) start with SELECT and (b) contain no
  INSERT/UPDATE/DELETE/DROP/ALTER keywords. The LLM can only ever read
  data, never modify it, even if a prompt somehow produced unexpected SQL.

- **Full result tables are rendered from the database, not the LLM.** The
  API returns the complete matching row set alongside the LLM's short
  summary sentence. The UI displays that data directly. Early versions
  had the LLM try to list every matching row itself, which was both
  wasteful (extra tokens) and unreliable (it would sometimes miscount
  rows when summarizing a partial sample) - this was found and fixed
  during testing (see Known limitations).

## Model and tools used

| Component | Tool |
|---|---|
| Language | Python 3.9+ |
| Database | SQLite (via `sqlite3` + `pandas`) |
| LLM | Groq free tier, model `openai/gpt-oss-120b` |
| REST API | FastAPI + Uvicorn |
| UI | Streamlit (chat interface) |
| LLM client | `groq` Python SDK |

`openai/gpt-oss-120b` was chosen after checking which models were
actually available on a free-tier Groq account (some models, like
`llama-3.3-70b-versatile`, returned a 404 for this account tier). It's a
reasoning model, which required two adjustments: `reasoning_effort="low"`
and a higher `max_tokens` ceiling, because reasoning models can otherwise
spend their whole token budget on internal reasoning and return an empty
final answer.

## Example queries and outputs

**Q: "How many tickets are currently open?"**
> There are currently 111 open tickets.

**Q: "Which agent has the lowest average customer rating?"**
> The agent with the lowest average customer rating is AGT-08, with an
> average rating of 3.48.

**Q: "Show me all Critical tickets not resolved within 12 hours."**
> Total matching tickets: 34. Criteria: Priority = Critical and the
> ticket was not resolved within 12 hours (either still unresolved or
> resolved after more than 12 hours).
*(Full 34-row table also rendered below the answer in the UI.)*

**Q: "Which agent resolved the most tickets this month?"**
> The agent who resolved the most tickets this month is AGT-01, with 16
> tickets resolved.
*("This month" is resolved relative to the dataset's own latest date,
not the real calendar month.)*

**Q: "Are there any anomalies in resolution times this week?"**
> [Summarizes the tickets flagged by the long-resolution-time rule whose
> creation date falls in the last 7 days of the dataset's timeline.]

## Known limitations

- **Hardcoded to this ticket schema.** The table schema description
  (given to the LLM) and the two anomaly rules are written specifically
  for this dataset's columns. Pointing the system at a CSV with a
  different structure (e.g. sales data) would require updating
  `get_schema_description()` and `anomalies.py` by hand. A more general
  version would auto-derive the schema description from the CSV's actual
  columns/dtypes at load time, and make anomaly rules configurable rather
  than hardcoded.

- **"Relative time" is dataset-relative, not wall-clock.** Since this is
  a static historical snapshot, "today"/"this week"/"this month" are
  interpreted relative to the latest timestamp in the CSV, not the real
  current date. This is the correct behavior for a snapshot dataset, but
  would need to switch to `datetime.now()` for a live, continuously
  updated ticket system.

- **LLM count accuracy required extra guardrails.** Early testing showed
  the LLM would sometimes miscount rows when writing a summary sentence
  (e.g. reporting 30 instead of the correct 34) if the true count wasn't
  stated unambiguously in the prompt. Fixed by explicitly labeling the
  total count as its own field in the prompt, separate from the sampled
  row data, and instructing the LLM not to count rows itself.

- **No conversation memory in the LLM calls themselves.** The Streamlit
  UI keeps a visual chat history, but each question is sent to the LLM
  independently - there's no "and what about last week?" follow-up
  support without repeating context.

- **Free-tier rate limits.** Groq's free tier has request-per-minute
  limits; heavy concurrent use could hit them. Not an issue for this
  assessment's scale.

## What I'd improve with more time

- Auto-generate the schema description from the CSV instead of hand-writing it, so the system generalizes to other datasets
- Add automated tests (currently verified manually against the raw CSV during development)
- Add simple conversation memory so follow-up questions can reference the previous answer
- Containerize with Docker for a true one-command, environment-independent setup
