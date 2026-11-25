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
- [x] T3 — **DONE 2026-11-24/25.** PR #1 merged to main as `1b9b1ec` (merge commit, done by Claude via `gh` after the user's OK because the browser showed a false "no push access"). Render redeployed; the webhook route went 404 → 401 without secret; the user ran setWebhook; **the bot answers in Telegram (user-confirmed)**. Note: Telegram's `last_error_message` is a sticky historical record, not a health signal. Original scope: Telegram bot: `POST /telegram/webhook` with secret-token check, reusing catalog_assistant; tests; set webhook to the Render URL. Needs a BotFather token. Route: delegated writer (2+ non-trivial files).
  - [x] Code (2026-11-24) on branch `feat/telegram-bot`, commit `1ba122b`: new `backend/telegram_bot.py` (TelegramConfig, `verified_update` secret check via hmac.compare_digest → 401 / 503 when unconfigured, TelegramSender port + httpx adapter, plain text, 10 s timeout, 4096-char cap, httpx logger at WARNING so the token never leaks), route in `main.py` (immediate ack, rollback before the LLM, BackgroundTasks), httpx pinned in requirements, README section. RED: ModuleNotFoundError telegram_bot; GREEN: `pytest -q` → 95 passed (parent spot check: 95 passed).
  - Also commit `2e7ad5e` `chore: ignore local skill registry` (`.atl/` made assess unassessable).
  - [x] Native review (2026-11-24, consent granted): lineage `review-03c5f9ba7b5fada1`, 1 lens `review-reliability` → approved, no blocking findings; acknowledged, authority `burned`. Reviewed boundary advances to `b60aa08`.
  - [x] User side: bot created in BotFather, both env vars loaded in Render, PR merged, setWebhook run. All done.
  - Known follow-up: no `update_id` de-duplication. A cold start longer than Telegram's delivery timeout could produce duplicate replies; consider a small in-memory recent-update_id set.
  - Earlier assess: the first run said `unassessable` (untracked .atl). After ignoring it: medium, `slice_budget_reached` (827 lines).
- [x] T4 — DONE 2026-11-25 (PR #4; live alert verified by the user). Slack Option B: product-created webhook (non-blocking, timeout, failure-safe) + tests; Option A guidance (Vercel/GitHub app). Needs a Slack webhook URL.
  - [x] Code (2026-11-25) on `feat/slack-alerts`, commit `b576cea` (delegated writer). New `backend/slack_alerts.py` (`SlackNotifier` port, httpx adapter, 3 s timeout, single attempt, URL redacted from messages/repr/logs, `send_safely` swallows every failure), hook in `POST /api/v1/products` via `BackgroundTasks` (201 path only), name escaped (`&`, `<`, `>`) so `<!channel>` or `<@U>` cannot mention, capped at 100 chars. Writer found a real bug: background tasks run before the session teardown, so the route now calls `db.close()` before returning to free the pooled connection (product stays serializable). RED: `ModuleNotFoundError: slack_alerts`; GREEN 132 passed (95 baseline). Parent spot check: 132 passed.
  - [x] Native review: user granted consent; lineage `review-5032b42d3e57c46e`, medium, 478 lines, 1 lens → APPROVED with no findings, acknowledged, burned. Boundary advances to `b576cea`.
  - [x] User side: Slack workspace "Catalogo de Productos", app "Catalogo Alertas", Incoming Webhook created. The user is adding `SLACK_WEBHOOK_URL` in Render (Claude never sees the value).
  - [x] PR #4 merged to main as `c0856ad` (user asked to merge, 2026-11-25). `SLACK_WEBHOOK_URL` is set in Render by the user.
  - [ ] Pending: live check (create a product from the web page, see the message in the Slack channel). Rubric #5 is verified only after that.
  - [ ] Option A (deploy alerts via the Vercel/GitHub Slack app) is guidance only; do it after Vercel exists (T7).
- [~] T5 — SKIPPED by the user (2026-11-25: "no usaremos devin"). Rubric #4 unmet, knowingly.
  - Decision (user, 2026-11-24): Devin does a **bug fix**, not the boilerplate. Claude builds the frontend independently (T6); after it exists, Claude writes a prompt for a small real bug for the user to hand to Devin.
- [x] T6 — DONE (PRs #2, #3, #5). Frontend (React + Vite + Tailwind) built by Claude (not on Devin output): catalog grid, form, Q&A panel, cold-start state. Aesthetic direction to be decided with the user.
  - Decision (user, 2026-11-24): **no 3D element at all.** The user was told explicitly that this leaves rubric #7 unmet and chose it anyway. R3F is dropped from the stack.
  - Aesthetic (user, 2026-11-24): design-taste-frontend direction **The split stage** (seed 1061525746, sheet in `.taste-skill/`). Work Sans 300/400/500; palette "Sand and moss" (bg #ddd6c6, surface #d2cab8, ink #2a2a26, muted #59574e, accent #4f6238, field #3f5a2a); stripe band as the only ornament. Adaptation chosen by the user: the sticky half is the **Q&A chat** (not a photo); the scrolling half holds the catalog list and the add-product form. On a phone, the chat goes in a tab or at the end.
  - T6a STATUS (2026-11-24): code committed `a962a7e` on `feat/web-frontend-chat`. The writer agent was stopped by the user before reporting; parent verified: `npx vitest run` → 29 passed (5 files), `npm run build` OK, taste `lint.mjs` → 0 FAIL 0 WARN. `inspect.mjs`: 4 FAIL, 1 WARN, all defended: few-pictures and no-footage (the fixed half is the chat, user's choice), focal-point (64px headline, accepted for now), covered-text @768 (fixed tab bar over the footer while scrolling; content has bottom padding), off-centre @768 (measured in the API-error state, short error text). No RED evidence recorded for the writer's tests (it was stopped); noted honestly. Assess: medium, `slice_budget_reached` (5008 lines, lockfile included). Native review: user granted consent; lineage `review-8f1c43b66248ad39`, 1 lens `review-reliability` → APPROVED with no findings, acknowledged, authority `burned`. Reviewed boundary advances to `a962a7e`. Follow-up (reviewer observation, not a finding): `CatalogList` groups by `stock > 0` / `stock === 0`, so a row with negative stock (possible from Supabase dashboard inserts, which skip API validation) would count in the total but show in neither group; fix in T6b by grouping `stock <= 0` as out of stock.
  - Telegram env vars: the user confirmed (2026-11-24) that TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET are loaded in Render. Pending: PR of `feat/telegram-bot` to main, then the user runs setWebhook.
  - T6b STATUS (2026-11-25): commit `de87caf` on `feat/web-frontend-catalog` (delegated writer; RED observed: missing-module imports and a failing negative-stock assertion; GREEN 60 tests, then 62). Parent spot check: `vitest run` 60 passed, `npm run build` OK. Add-product form (client validation mirrors the API), `createProduct` with `maxAttempts: 1` so a POST is never auto-retried, insert-by-id list update (no reload, no duplicates), negative-stock grouping fix. Inspect: only the known defended FAILs. Native review: user granted consent; lineage `review-8a501183febb0d16`, medium, 1061 lines → APPROVED, acknowledged, burned; reviewed boundary advances to `de87caf`. Informational finding fixed after the review (parent, test-first, RED then GREEN): `parsePrice` accepted `0x1A`/`1e3` via `Number()`; now a strict decimal regex (this follow-up commit is not itself reviewed; tiny and covered by 2 new tests). Backend follow-up (outside this slice): `ProductBase.stock` has no upper bound, so a value above int32 sent straight to the API would likely 500.
  - Slices (stacked-to-main, on top of `feat/telegram-bot`): T6a `feat/web-frontend-chat`: Vite + React + Tailwind scaffold, tokens, API client with the cold-start state, split layout, chat panel (`/api/v1/catalog/ask`). T6b `feat/web-frontend-catalog`: catalog list (GET) + add-product form (POST) with refresh.
- [x] T7 — Vercel deploy (2026-11-25): https://product-catalog-dun.vercel.app , Hobby plan, imported as a single project with Root Directory `frontend` (Vercel detected two apps; "Services" would also have deployed the backend, so it was avoided), `VITE_API_URL` set before the first deploy. Render `ALLOWED_ORIGINS` set to that origin by the user. Parent verified with curl: GET and the `/catalog/ask` preflight return the matching `access-control-allow-origin`; a foreign origin gets none. Rubric #3 deployed; the user still has to confirm the chat works in the browser. Rubric #7 (3D) intentionally not done (user decision).
- [x] T6c — Redesign (2026-11-25, user asked: English UI and "ugly" colors). Branch `feat/frontend-redesign`, commit `2b54d88` (delegated writer) plus a parent follow-up. Spanish UI (neutral "tú", es-locale numbers), new palette (bg #f5f7fa, ink #121c2b, accent #1d5fbf, navy chat panel #12263f), stripe ornament removed, headline enlarged (inspect: 1 FAIL few-pictures and 2 WARN accepted). Deliberate redraw of the dealt palette, reason: user rejection. Native review: granted, lineage `review-8a8e219eb05054de`, APPROVED, acknowledged, burned. Finding (WARNING, valid): a single-separator "1.000"/"1,000" would silently save as 1. Fixed test-first (RED then GREEN): the price accepts one decimal comma or dot, at most 2 decimals, and rejects 3+ decimals with an explicit message. 63 tests pass. That fix is not reviewed separately. Pending: user OK to push, PR and merge.
- [~] T8 — Comentera SKIPPED by the user (2026-11-25: "lo de comentera lo dejamos, no se hace"). Rubric #6 unmet, knowingly. The final report / video source document is still open (see Next step).

## Checks
- Backend: `backend/venv/Scripts/python.exe -m pytest -q` (59 passing baseline).
- Live: curl the Render URL (GET 200, POST 201), send a Telegram message, check the Slack channel, open the Vercel URL.

## Delivery
- Forecast is ~1,200+ authored lines (frontend dominates), over the ~400 budget. Strategy `ask-on-risk`; chain strategy chosen by the user (2026-11-24): **stacked-to-main**. Stack: PR1 `feat/telegram-bot` → main; PR2 `feat/web-frontend-chat` (based on PR1); PR3 `feat/web-frontend-catalog` (based on PR2).
- RDD becomes applicable once the git repo exists.

## Progress / Evidence (snapshot 2026-11-25, session paused by the user)

### Rubric status
| # | Item | Status |
|---|------|--------|
| 1 | Supabase `products` with real rows | Done (24 rows: 4 original + 20 added by Claude directly in SQL on 2026-11-25, so Slack was not flooded) |
| 2 | Render API GET 200 / POST 201 | Done |
| 3 | Vercel frontend online | Done: https://product-catalog-dun.vercel.app (Spanish UI, professional palette, user: "mucho mejor") |
| 4 | Devin log | Skipped by the user |
| 5 | Slack alerts | Done and verified live |
| 6 | Comentera, 2 comments | Skipped by the user |
| 7 | 3D element | Skipped by the user |
Extra: Telegram bot (live), CI on GitHub Actions, conversation memory.

### Live system (public URLs only; never store tokens or webhook URLs here)
- Repo: https://github.com/marcovelaa/product-catalog (public, only `main` exists, 11 PRs merged with merge commits)
- API: https://product-catalog-8ej9.onrender.com (Render free; sleeps after 15 min idle)
- Web: https://product-catalog-dun.vercel.app (Vercel Hobby, Root Directory `frontend`, `VITE_API_URL`)
- Supabase project `product-catalog`: tables `products` (RLS on, 1 public read policy) and `telegram_messages` (RLS on, 0 policies, created 2026-11-25 via migration `create_telegram_messages`)
- Render env var NAMES in use: DATABASE_URL (pooler), ALLOWED_ORIGINS, GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, TELEGRAM_ADMIN_IDS, SLACK_WEBHOOK_URL
- Tests: backend 464 passed, frontend 64 passed; CI runs both on every PR and on main (public repo + standard runners = free)

### PRs (all merged)
#1 Telegram bot, #2 web chat + catalog, #3 add-product form, #4 Slack alert, #5 Spanish UI + palette, #6 stock cap (API 500 fixed with a 422), #7 Spanish bot texts + duplicate-delivery guard, #8 CI, #9 admin allow-list + /id + /productos, #10 /agregar + /editar, #11 conversation memory + Spanish-only answers.

### Bot capabilities now
Q&A over the live catalog (Gemini, Spanish only), memory of the last 10 messages per chat, `/olvidar`, `/id`, `/productos`, admin-only `/agregar` and `/editar` (allow-list of SENDER ids, fail closed; no public write route exists), Slack alert on `/agregar`. Details: `odd/tasks/telegram-admin-commands.md`.

### Decisions by the user (2026-11-25)
No 3D, no Devin, no Comentera; commands (not natural language) for writes; everything on free tiers; AI use for the video is authorized by the course; the video must be about how to integrate an agent bot into a system; any amount of time over one minute is fine; currency should be bolivianos (Bs).

### Honest notes for the report/video
The bot is a conversational assistant with deterministic commands, not an autonomous agent (writes are never decided by the LLM). Duplicate guard is in memory (lost on restart). The web chat has no memory. Unreviewed small follow-ups were accepted by the user to avoid review loops. Supabase advisor: `public.rls_auto_enable()` is a pre-existing SECURITY DEFINER function callable by anon via RPC (likely platform-managed with the `ensure_rls` event trigger); NOT touched, user may ask Claude to investigate.

## Next step (paused 2026-11-25)
1. Live check of memory, Spanish-only answers and `/olvidar` in Telegram (user was asked to test; result not yet reported).
2. Currency in bolivianos (Bs): waiting for the user to say whether to only relabel or also convert values (and which exchange rate; Claude must not assert a rate). Touches web list and form hint, bot formatting, assistant instruction. `Intl.NumberFormat("es-BO",{style:"currency",currency:"BOB"})` gives `Bs 25,50`.
3. Video support material for NotebookLM, in a folder OUTSIDE the repo (e.g. `E:\USUARIOS\Desktop\video-proyecto`): a Markdown source document centered on integrating an agent bot into a system (system + agent + two channels, webhook, ack-then-background, grounding with live data, authorization, memory, duplicates, failure isolation, tests/CI, free tiers, what was skipped), an architecture diagram, and FRESH screenshots (old ones in `video-proyecto/capturas` show deleted test products and the old hint). Plan: hybrid video (NotebookLM explains, user adds real screen clips of web, bot and Slack in a free editor); NotebookLM Video Overview accepts a steering prompt, a visual style and a language, and is not confirmed to reuse uploaded screenshots.
4. Optional: investigate `rls_auto_enable()`; Slack Option A (deploy alerts via Vercel/GitHub app); photos (T5 of the admin feature, Supabase Storage).
