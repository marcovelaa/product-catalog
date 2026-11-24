# Feature: products-backend

Locator: `odd/tasks/products-backend.md` · Engram mirror: `odd/products-backend/tasks`

## Objective
Build the FastAPI backend from Phase 1.2 of the final-project guide: a single `products` table on Supabase Postgres, with GET/POST endpoints, ready to run locally and deploy to Render.

## Problem / Why
The project folder is empty. The guide's code has inconsistencies: the SQL schema doesn't match the ORM model, it falls back to psycopg3 while using a psycopg2 URL, and it combines CORS `*` with credentials. The user asked for the backend, ready for them to paste secrets into `.env`.

## Scope (authorized)
- `backend/` only: app code, pinned requirements, `.env.example`, `.gitignore`, SQL schema, tests, README.
- Out of scope until the user decides: the LLM integration (feature and provider unknown), Slack webhook, render.yaml/vercel.json, frontend.

## Constraints
- Python 3.13 (`py -3.13`); the system `python` is 3.10.6.
- No git repo exists, so work-unit commits are not applicable until the user creates one (the guide pushes `backend/` as its own repo).
- No real secrets in files; `.env` is gitignored, `.env.example` holds placeholders only.

## Tasks
- [x] T1 — Backend core + tests (route: delegated, writer trigger fired: 2+ non-trivial files)
  - Evidence: RED was `ModuleNotFoundError: No module named 'models'`; GREEN was `pytest -q` → 19 passed (parent spot check, re-run: 19 passed, 1 warning).
  - Gap: `.env` / `.env.example` NOT written. The Write tool is denied by a permission rule for those files, and it was not bypassed. The user creates them.
  - Follow-up folded into T2: ProductResponse inherits the input constraints, so a row inserted directly in the DB with a blank name makes GET return 500.
- [x] T2 — Catalog Q&A with Gemini (route: delegated, same writer continued; touches main.py, requirements, env, new module, tests)
  - Evidence: RED was `ModuleNotFoundError: catalog_assistant`, and the T1 bug reproduced as GET 500; GREEN was `pytest -q` → 49 passed, 0 warnings (parent spot check re-run: 49 passed).
  - Additions: 30 s HTTP timeout (the SDK default is none), a catch-all → 502, and a single AssistantError exception handler. With no key, 503 takes precedence over 422 because dependencies run before body validation.
  - Verification tier: RDD assess unavailable (no git repo) → treated as high → independent verifier. The first run was stopped by the user and relaunched on request. Result: 49 passed, no blockers.
    - Should-fix: `main.py:105-108` holds a pooled DB connection during the Gemini call (~15 concurrent asks exhaust the pool → CRUD hangs/500s). Fix: materialize DTOs + rollback before `answer()`.
    - Minor: (a) thinking may eat the 512-token budget, so set ThinkingLevel.MINIMAL + log finish_reason (needs a live smoke test); (b) the timeout is per request with automatic_continuation, so set it False; (c) the README lacks Render Root Directory `backend`; (d) the README lacks password URL-encoding.
- [x] T3 — Apply verifier findings (should-fix + minors a–d). Authorized by the user on 2026-11-11. Route: delegated (same writer continued).
  - Evidence: RED was 7 failed / 49 passed for the intended reasons; GREEN was `pytest -q` → 56 passed, 0 warnings (writer).
  - Changes:
    - frozen CatalogProduct snapshots + `db.rollback()` before `answer()`
    - max_output_tokens=1024, finish_reason/block_reason logged, MAX_TOKENS/CONTINUATION return the text with a warning
    - `automatic_continuation=False` (types.py:6808)
    - README: Root Directory, password encoding, plain-text rendering of the answer
- [x] T4 — Live smoke test with the real Supabase + Gemini (user's `.env`), then decide thinking_config.
  - First run: the server crashed with `ModuleNotFoundError: psycopg`. SQLAlchemy 2.1 maps a driverless `postgresql://` URL to psycopg 3 (`sqlalchemy/dialects/postgresql/__init__.py:99`).
  - Fix (inline, 2 small files): `database._pin_postgres_driver` rewrites `postgresql://` / `postgres://` → `postgresql+psycopg2://`. RED: 2 failed; GREEN: `pytest -q` → 59 passed.
  - Live results:
    - `/health` 200; GET 200 `[]`; 2× POST 201 (created "Wireless Mouse" and "Mechanical Keyboard" in the user's real DB); GET 200 lists both
    - `/catalog/ask` 200 with correct Spanish answers in 4.2 s and 13.1 s; no finish_reason warnings logged
  - Decision: no `thinking_config` needed, since answers were complete with gemini-3.5-flash-lite.
  - Note: curl from Git Bash sent non-UTF-8 bytes for "¿/é", which returned 400 "error parsing the body". That is a client encoding issue, not the backend; JSON `\u` escapes worked.
  - (a) No thinking_config yet: an unsupported field would 400 every call. Instead: max_output_tokens=1024, log finish_reason, and treat empty text as 502. Thinking config is decided after the live smoke test (once Supabase is up).
  - User status (2026-11-11): `.env` created with GEMINI_API_KEY only. The Supabase project doesn't exist yet, and the app can't start without DATABASE_URL (fail fast by design).
  - `.env` / `.env.example`: content handed to the user (the Write tool is denied by a permission rule).
  - Decision (user, 2026-11-11): free Gemini model; users ask questions about the catalog.
  - Design: `POST /api/v1/catalog/ask` {question} → {answer}. The catalog (capped) is stuffed into the system instruction, and the model has no tools. Provider adapter behind a port, with domain errors mapped to 429/502/503. `GEMINI_API_KEY` + `GEMINI_MODEL` (default `gemini-3.5-flash-lite`: stable and free tier per aistudio.google.com/docs/models + /pricing, checked 2026-11-11). SDK: `google-genai`.
  - Tradeoff: context stuffing only scales to a few hundred products. The endpoint is public, so anyone can burn the free quota (documented in the README, no rate limiter in the MVP).

- [x] T5 — Verify DATABASE_URL ownership and re-run smoke test (reopened and closed 2026-11-24)
  - ~~Initial finding: DATABASE_URL points to a third-party DB.~~ RETRACTED 2026-11-24: Supabase MCP shows project `product-catalog` (ref `duapmqpzcamujttrznoo`, ca-central-1, created 2026-11-10) in the user's org, and the user confirmed the `.env` host contains that ref. The DB is the user's own; T4 writes went to their DB. No instructor notification needed.
  - Project status was INACTIVE (paused, free tier) → restore, verify `products` table, then re-run smoke test.
  - [x] Step 1 (2026-11-24): restored, status Healthy. `public.products` matches `sql/schema.sql` (bigint identity id, numeric price, stock default 0, nullable image_url, created_at default utc now), RLS enabled. Rows: id 1 "Wireless Mouse" 25.5, id 2 "Mechanical Keyboard" 89.99 (both from T4, 2026-11-11).
  - [x] Step 2 (2026-11-24, local uvicorn + user's `.env`): `/health` 200; GET 200 (2 rows); POST 201 (id 3 "USB-C Hub" 34.9, stock 12, now in the user's DB); invalid POST 422; GET 200 (3 rows); `/catalog/ask` 200 in Spanish (3.7 s) and English (1.4 s) with the correct cheapest product.
  - Note: an inline `-d` body from Git Bash curl again returned 400 "error parsing the body"; the same JSON sent via `--data-binary @file` returned 200. This is a client-side issue, not the backend.

## Acceptance criteria
- `pytest` passes: GET returns 200 with a list, POST returns 201 with an id, invalid payloads return 422.
- The ORM model matches `sql/schema.sql` (bigint id, numeric price, created_at).
- The app fails fast with a clear error when `DATABASE_URL` is missing.
- CORS origins come from an env var.

## Checks
- `py -3.13 -m venv` + `pip install -r requirements-dev.txt` + `pytest -q` inside `backend/`.

## Delivery
Forecast is ~350 authored lines, so the strategy is `ask-on-risk` (under budget). Commits are not applicable (no repo). RDD review is not applicable (no repo).

## Progress / Evidence
- T1–T5 done. 59 tests pass; live smoke test against the user's own Supabase project (`product-catalog`) passed on 2026-11-24.

## Next step
User decision: deploy to Render (Root Directory `backend`, Supabase pooler URL, not the IPv6-only direct host) and/or create the git repo for `backend/`.
