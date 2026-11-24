# Feature: final-project-delivery

Locator: `odd/tasks/final-project-delivery.md` · Engram mirror: `odd/final-project-delivery/tasks`

## Objective
Deliver the full course guide (Phases 1.3, 2 and 3) and meet all 7 rubric items, built better than the guide's template, plus a Telegram bot as an extra channel for the catalog Q&A.

## Problem / Why
The backend (`products-backend`, T1–T5) works locally against the user's Supabase project, but nothing is public yet: no repo, no Render deploy, no frontend, no Slack, no Comentera, no Devin log. The user wants a non-generic result plus Telegram (decision 2026-11-24).

## Rubric (source: course guide, "Rúbrica de Verificación")
1. Backend/DB: `products` persists real rows in Supabase. **Done** (products-backend T5).
2. API: the Render service returns 200 on GET and 201 on POST.
3. Frontend on Vercel: online and updates on reload or when an item is added.
4. Devin: the report includes the Devin log/prompt (the guide allows either the frontend boilerplate or a bug fix).
5. Slack: the channel shows deploy alerts or product-created alerts.
6. Comentera: at least 2 review comments on the UI.
7. 3D: an interactive 3D element is visible on screen.

## Improvements over the guide (planned)
- Monorepo (`backend/` + `frontend/`) with Render Root Directory `backend` and Vercel Root Directory `frontend`, instead of two repos.
- Render free-tier cold start (~1 min) handled in the UI with a "waking up the server" state, instead of a broken-looking page.
- 3D viewer driven by the selected product, not a static indigo box.
- Catalog Q&A (`/api/v1/catalog/ask`) exposed in the web UI and in Telegram.
- Slack: both options. Option B is a backend webhook on product creation (non-blocking, with a timeout, never failing the POST). Option A is the Vercel/GitHub app for deploy alerts.
- CORS restricted to the Vercel origin via env var (already supported).
- Guide bugs already fixed in the backend: schema/ORM mismatch, psycopg3 fallback, CORS `*` with credentials, and the direct IPv6 host on Render (use the pooler URL).

## Scope (authorized 2026-11-24: "everything in the guide, better, plus Telegram")
- Repo setup, Render config, Telegram webhook, Slack webhook, frontend, Vercel config, README/report material.
- Remote actions (GitHub push, Render/Vercel/Slack/Telegram setup) need explicit user authorization per destination and credential. Claude never reads or writes `.env`.

## Constraints
- Free tiers only: Render (sleeps after 15 min idle, ~1 min wake), Vercel, Supabase (auto-pauses when idle), Telegram Bot API (free).
- Python 3.13 venv in `backend/venv`. Git Bash curl mangles inline non-ASCII JSON, so use `--data-binary @file`.
- Devin must be run by the user (it is their account and their log). Its free availability is unverified.

## Tasks
- [x] T1 — Monorepo git init at project root + root `.gitignore` + first commit; GitHub remote (user's account). Route: inline (mechanical).
  - [x] Local (2026-11-24): `git init -b main`, root `.gitignore` (.env, venv, node_modules, .claude/settings.local.json). Staged scan: no `.env` staged, `.env.example` has placeholders only, the only URL matches are test fixtures. Commit `bd45359` (no AI attribution, per the user's rule).
  - [x] Remote (2026-11-24, user-authorized: repo name, public, their gh session): https://github.com/marcovelaa/product-catalog created via `gh repo create --public --source=. --push`; `main` tracks `origin/main`.
  - RDD: the hook-triggered review of the doc-only workspace change returned low risk / approved; `acknowledge-approved` was denied by the Claude Code permission classifier and handed to the user.
- [x] T2 — Render deploy of `backend/` (render.yaml or dashboard settings, pooler DATABASE_URL, CORS env, GEMINI vars); verify rubric #2 live. Route: inline (user-driven dashboard config).
  - Service `product-catalog` at https://product-catalog-8ej9.onrender.com (free, Virginia, Root Directory `backend`, Python 3.13 from `.python-version`, dashboard config with no render.yaml). First deploy from commit bd45359.
  - First smoke test: GET/POST/ask → 500. Diagnosed via Supabase `query_logs`: supavisor "password authentication failed for user postgres". Cause: the user had duplicated the `postgresql://postgres.<ref>` prefix in DATABASE_URL, so the password parsed wrong. Fixed by the user in Render → Environment.
  - Live evidence (2026-11-24 22:17 UTC): `/health` 200; GET 200 (3 rows); POST 201 id 4 "Laptop Stand"; invalid 422; `/catalog/ask` 200 in Spanish; row id 4 confirmed in Supabase via MCP SQL. **Rubric #1 and #2 verified.**
  - Security follow-up DONE (2026-11-24): DB password rotated by the user (the first attempt didn't take; the second succeeded). Verified: local `.env` connects (4 rows), Render GET 200 at 22:32:45 UTC, invalid 422, ask 200. ALLOWED_ORIGINS stays unset until Vercel exists.
- [ ] T3 — Telegram bot: `POST /telegram/webhook` with secret-token check, reusing catalog_assistant; tests; set webhook to the Render URL. Needs a BotFather token.
- [ ] T4 — Slack Option B: product-created webhook (non-blocking, timeout, failure-safe) + tests; Option A guidance (Vercel/GitHub app). Needs a Slack webhook URL.
- [ ] T5 — Devin prompt (non-generic) for the user to run; capture the log for the report.
- [ ] T6 — Frontend (React + Vite + Tailwind + R3F) on top of the Devin output: catalog grid, form, product-driven 3D viewer, Q&A panel, cold-start state. Aesthetic direction to be decided with the user.
- [ ] T7 — Vercel deploy (Root Directory `frontend`, `VITE_API_URL`), then update the Render CORS origin; verify rubric #3 and #7.
- [ ] T8 — Comentera embed/setup + gather 2+ comments (rubric #6); final report checklist mapping each rubric item to evidence.

## Checks
- Backend: `backend/venv/Scripts/python.exe -m pytest -q` (59 passing baseline).
- Live: curl the Render URL (GET 200, POST 201), send a Telegram message, check the Slack channel, open the Vercel URL.

## Delivery
- Forecast is ~1,200+ authored lines (frontend dominates), over the ~400 budget. Strategy `ask-on-risk`: ask for the chain strategy before the commit that crosses the budget.
- RDD becomes applicable once the git repo exists.

## Progress / Evidence
- (none yet)

## Next step
T3: Telegram bot on branch `feat/telegram-bot` (delegated writer, code first). The user creates the bot in @BotFather and adds TELEGRAM_BOT_TOKEN + TELEGRAM_WEBHOOK_SECRET to Render.
