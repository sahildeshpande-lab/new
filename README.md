# Devita Reporting Backend

Python FastAPI backend for read-only MySQL reporting with Gemini LLM based natural-language SQL generation and report writing.

V1 connects to MySQL, reads live schema information from `information_schema`, grounds the LLM with `reporting_metadata.json`, asks Gemini to generate safe MySQL SELECT queries, executes those queries, and returns report-ready rows plus a generated report summary.

## Supported V1 Reports

- Attendance Report
- Timesheet Report
- Team Lead Timesheet Report
- HR Timesheet Report

## Setup

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Update `.env` with your MySQL/phpMyAdmin-hosted database credentials:

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=devita_project_management
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_SSL_DISABLED=true
GEMINI_API_KEY=your_gemini_key
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GEMINI_MODEL=gemini-2.5-flash-lite
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=2500
```

`GEMINI_MODEL` defaults to `gemini-2.5-flash-lite`, which Google lists on the Gemini API pricing page with free-tier usage.

## Run

```powershell
uvicorn app.main:app --reload
```

Open:

- `GET http://127.0.0.1:8000/health`
- `GET http://127.0.0.1:8000/llm/health`
- `GET http://127.0.0.1:8000/reports`
- `GET http://127.0.0.1:8000/schema/summary`
- `GET http://127.0.0.1:8000/schema/effective-metadata`

Detailed endpoint and use-case documentation is in [docs/REPORTING_BACKEND.md](</C:/Users/sahil - Solace/Documents/New project/docs/REPORTING_BACKEND.md>).

## Example Requests

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/reports/query -ContentType 'application/json' -Body '{
  "question": "show attendance report for March 2026",
  "limit": 50
}'
```

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/reports/timesheet_report/run -ContentType 'application/json' -Body '{
  "filters": {
    "date_from": "2026-03-01",
    "date_to": "2026-03-31",
    "project_id": 10
  },
  "question": "Generate a timesheet report for project 10 in March 2026",
  "limit": 100
}'
```

## Safety Rules

- Only reports declared in `reporting_metadata.json` are supported.
- All report query endpoints use Gemini to generate the SQL plan.
- Gemini is also used after data fetch to generate the written report summary.
- LLM-generated SQL is validated before execution.
- SQL can reference only tables and columns declared in `reporting_metadata.json`.
- All filters are bound parameters.
- Non-SELECT SQL is blocked.
- Multiple SQL statements are blocked.
- A `LIMIT :limit` parameter is required.
- Unsupported report requests return a clarification response.
- Reports, generated summaries, and testing data are not inserted into MySQL by this backend.

## LLM Flow

1. The API receives the user question.
2. The backend loads curated business metadata from `reporting_metadata.json`.
3. The backend tries to read the live MySQL schema summary from `information_schema`.
4. Gemini receives the question, metadata, live schema summary, filters, and row limit.
5. Gemini returns JSON containing `report_id`, SQL, params, expected columns, and report summary.
6. The backend validates read-only SQL and declared table/column usage.
7. The backend executes the query against MySQL.
8. Gemini summarizes the result rows into a business report narrative.
