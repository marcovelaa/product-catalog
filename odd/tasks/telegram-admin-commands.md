# Feature: telegram-admin-commands

Locator: `odd/tasks/telegram-admin-commands.md` · Engram mirror: `odd/telegram-admin-commands/tasks`

## Objective
Let the owner register and edit products from the Telegram bot with fixed commands, safely: only allow-listed Telegram users can write. Later phases add conversation memory and product photos.

## Problem / Why
The bot is read-only and public (it only answers catalog questions). The owner wants to manage the catalog from Telegram. The public REST API has no authentication, so edit capability must NOT be exposed as a public route; it lives behind the bot's admin check.

## Decisions (user, 2026-11-25)
- Commands, not natural language (precise, no LLM misreads). Natural language with confirmation was offered and declined.
- Only the owner can write; everyone else keeps the read-only Q&A.
- Everything must stay free (Render, Vercel, Supabase, Telegram, GitHub Actions on a public repo).

## Command design (Spanish replies, neutral "tú")
- `/id`: anyone; replies with the sender's Telegram user id (bootstrap for the allow-list).
- `/productos`: lists products with ids (read-only, no LLM call). Open to everyone.
- `/agregar Nombre; precio; stock; url opcional`: admin only. Separator is `;` because the price accepts a decimal comma (`25,50`).
- `/editar <id> campo=valor; campo=valor`: admin only. Fields: `nombre`, `precio`, `stock`, `imagen`. Partial update.
- Price rules match the web form: one decimal comma or dot, at most 2 decimals; stock 0 to 2147483647; name 1 to 200; image http(s) only, up to 2048 chars.
- Auth: env var `TELEGRAM_ADMIN_IDS` (comma-separated user ids). Empty or missing means admin commands are disabled for everyone (fail closed). Checked against the SENDER id (`message.from.id`), never the chat id.
- No public PATCH/PUT route. A bot-created product also triggers the existing Slack alert.

## Constraints
- Python 3.13 venv in `backend/venv`; `pytest -q` baseline 147 passed.
- Never read or write `.env`; never log tokens, secrets or the webhook URL.
- Keep the webhook acknowledging quickly; the duplicate-delivery guard stays.

## Tasks
- [x] T1 — DONE 2026-11-25 (commits 52f69f7 + parse_command fix). Admin foundation + read-only commands: parse `from.id`, `TELEGRAM_ADMIN_IDS` config (fail closed), `/id`, `/productos`, updated `/start` and `/ayuda` text (admin commands listed only for admins). Route: delegated writer.
- [x] T2 — DONE 2026-11-25 (commit b77f599). `/agregar` (+ Slack alert) and `/editar` through a shared product service (no public route), strict validation, clear Spanish errors, tests. Route: delegated writer.
- [ ] T3 — User steps: deploy, send `/id`, set `TELEGRAM_ADMIN_IDS` in Render, live check of `/agregar` and `/editar`.
- [ ] T4 — Conversation memory + Spanish-only answers (user decision 2026-11-25: "vamos con memoria y que solo responda español"). Table `telegram_messages` (RLS on, NO policies; the backend role bypasses RLS), keep only the last 10 messages per chat, `/olvidar` clears a chat, memory failures degrade silently to no memory. The shared assistant answers ONLY in Spanish (applies to web and Telegram; the web hint text is updated). Production DDL runs only after the user sees the exact SQL and says yes. Branch `feat/telegram-memory`. Route: delegated writer.
- [ ] T5 (later) — Product photos: Telegram photo to Supabase Storage (public bucket, new credential in Render), save `image_url`, bot can show it, web shows images.

## Checks
- Backend: `backend/venv/Scripts/python.exe -m pytest -q`.
- Live: `/id`, `/productos`, `/agregar`, `/editar` from the owner account; a non-admin account gets a polite refusal.

## Delivery
- Strategy `ask-on-risk`, chain `stacked-to-main` (chosen earlier by the user). One PR per work unit; native review per commit when `review_due`.

## Progress / Evidence
- T1 (2026-11-25): delegated writer. RED: `ImportError: cannot import name get_telegram_admin_ids`; GREEN 196 passed (baseline 147); parent spot check 196 passed, then 205 after the follow-up. Security reviewed by the parent: `parse_admin_ids` keeps only ASCII positive integers, fail closed when empty, `is_admin` uses the SENDER id (`message.from.id`), never the chat id. Native review: medium, 619 lines, lineage `review-1a67a470461f8e01`, approved, acknowledged, burned. One finding (valid): `parse_command` split only on a literal space, so `/agregar` followed by a newline was not recognized; fixed test-first (RED 3 failed, then GREEN 205 passed). That follow-up is a few lines and was not reviewed separately.

- T2 (2026-11-25): delegated writer, branch `feat/telegram-add-edit-products` stacked on T1. RED: `ModuleNotFoundError: product_service` (the Telegram tests were not observed RED on their own: the writer reported it honestly); GREEN 393 passed (baseline 205); parent spot check 393 passed. Parent read: the admin check runs BEFORE the payload is parsed, the DB write is inline before the ack, Slack and reply texts are built from a snapshot so background tasks hold no session, `finally: db.rollback()`. The public `POST /api/v1/products` now calls `product_service.create_product` with identical behavior (all its tests pass unchanged); no PATCH/PUT/DELETE route exists (a test asserts it). Native review: medium, 1280 lines, lineage `review-a9c6472d1751b652`, APPROVED with no findings, acknowledged, burned.

- T4 (2026-11-25): delegated writer, branch `feat/telegram-memory`, commit `95f3f28`. RED observed separately for memory tests (`ImportError ... MAX_HISTORY_MESSAGES`), Telegram flow tests (17 failed) and assistant tests (7 failed); GREEN backend 464 passed (baseline 393), frontend 64 passed, build OK; parent spot check identical. Memory: last 10 messages per chat, truncated to 1000 chars, `/olvidar`, reads degrade to no memory on any DB error, the turn is saved only after the reply was delivered, background save uses its own session. The shared assistant answers only in Spanish (web hint updated). Native review: medium, 1135 lines, lineage `review-36ccf9841c37841c`, APPROVED with no findings, acknowledged, burned. The SQL (`backend/sql/telegram_messages.sql`) is NOT applied until the user approves it.
- Open requests (user, 2026-11-25): (1) currency in bolivianos (Bs) across web, bot and assistant; waiting for the user to say whether to only relabel or also convert values and with which rate; (2) the video must be about how to integrate an agent bot into a system; (3) NotebookLM source document + diagram + fresh screenshots after this merges.

## Next step
Push both branches as stacked PRs (needs user OK), merge, then T3 user steps: `/id`, set `TELEGRAM_ADMIN_IDS` in Render, live check.
