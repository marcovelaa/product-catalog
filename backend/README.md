# Product Catalog API

FastAPI backend for a single `products` table on Supabase Postgres.

## Endpoints

| Method | Path               | Description                                  |
| ------ | ------------------ | -------------------------------------------- |
| GET    | `/health`          | Health check, no database access             |
| GET    | `/api/v1/products` | List products, ordered by id                 |
| POST   | `/api/v1/products` | Create a product (`201`), invalid data `422` |
| POST   | `/api/v1/catalog/ask` | Ask the catalog assistant (Gemini) a question |

## Prerequisites

- Python 3.13 (`py -3.13 --version`)
- A Supabase project

## 1. Create the table in Supabase

Open the Supabase dashboard -> SQL Editor, paste the contents of `sql/schema.sql`, and run it once.
The API never creates tables by itself, so this script is what enables Row Level Security.

## 2. Configure `.env`

Copy `.env.example` to `.env` (if it does not exist yet) and fill in the real values:

- `DATABASE_URL`: Supabase dashboard -> Project Settings -> Database -> Connection pooling -> **Session pooler** connection string.
  Keep the `postgresql+psycopg2://` prefix. Do not use the direct `db.<ref>.supabase.co` host: it is IPv6-only and Render cannot reach it.
  Use a database password with only letters and digits; otherwise URL-encode its special characters (`@ : / # ? %`), for example with `python -c "import urllib.parse; print(urllib.parse.quote('your-password', safe=''))"`.
- `ALLOWED_ORIGINS`: comma-separated list of frontend origins, for example `http://localhost:5173,https://my-app.vercel.app`.
- `GEMINI_API_KEY`: Google Gemini API key for the catalog assistant. Leave it empty to disable the assistant; the product endpoints keep working.
- `GEMINI_MODEL` (optional): Gemini model for the catalog assistant. Defaults to `gemini-3.5-flash-lite`.

> **Never commit `.env`.** It holds your database password and is already listed in `.gitignore`.

## 3. Set up a virtual environment (Windows PowerShell)

```powershell
py -3.13 -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
```

If PowerShell refuses to run `activate`, allow local scripts once and retry:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## 4. Run the API

```powershell
uvicorn main:app --reload --port 8000
```

Open <http://localhost:8000/docs> to try the endpoints.

## 5. Run the tests

```powershell
pytest -q
```

The tests use an in-memory SQLite database and a fake assistant. They never touch Supabase or Gemini.

## Catalog assistant (Gemini)

`POST /api/v1/catalog/ask` answers shopper questions using only the products in the catalog.

1. Create a free API key at <https://aistudio.google.com/apikey>.
2. Paste it into `.env` as `GEMINI_API_KEY=...` (and in Render's environment variables when you deploy). `GEMINI_MODEL` is optional.
3. Restart the API and try it at <http://localhost:8000/docs>, or with curl:

```bash
curl -X POST http://localhost:8000/api/v1/catalog/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Do you have keyboards under 100?"}'
```

Response: `{"answer": "..."}`. The frontend must render `answer` as plain text, never as HTML. Errors: `422` invalid question (empty or over 500 characters), `503` no API key configured, `429` Gemini quota exceeded, `502` Gemini failed or returned no answer.

Notes:

- Free-tier limits are low and apply per Google Cloud project, not per API key.
- The endpoint is public: anyone who finds it can spend your quota. This MVP has no rate limiter.
- Only the first 200 products (by id) are sent to the model as context.
- The model has no tools: it can only answer from the catalog text it receives, and it can never read or modify the database.

## Deploy to Render

Create a **Web Service** from the GitHub repository that contains this folder:

| Setting           | Value                                              |
| ----------------- | -------------------------------------------------- |
| Root Directory    | `backend` (leave empty if `backend/` itself is the repo root) |
| Build Command     | `pip install -r requirements.txt`                  |
| Start Command     | `uvicorn main:app --host 0.0.0.0 --port $PORT`     |
| Health Check Path | `/health`                                          |
| Environment vars  | `DATABASE_URL`, `ALLOWED_ORIGINS`, `GEMINI_API_KEY`, optional `GEMINI_MODEL` (same as `.env`) |

Render reads `.python-version` to use Python 3.13.
