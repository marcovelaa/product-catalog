# Product Catalog API

FastAPI backend for a single `products` table on Supabase Postgres.

## Endpoints

| Method | Path               | Description                                  |
| ------ | ------------------ | -------------------------------------------- |
| GET    | `/health`          | Health check, no database access             |
| GET    | `/api/v1/products` | List products, ordered by id                 |
| POST   | `/api/v1/products` | Create a product (`201`, optional [Slack alert](#slack-alerts)), invalid data `422` |
| POST   | `/api/v1/catalog/ask` | Ask the catalog assistant (Gemini) a question |
| POST   | `/telegram/webhook` | Telegram bot webhook (see [Telegram bot](#telegram-bot)) |

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
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` (optional): enable the Telegram bot. Leave them empty to disable it; the rest of the API keeps working.
- `TELEGRAM_ADMIN_IDS` (optional): comma-separated Telegram user ids allowed to use the bot's admin commands (see [Admin commands](#admin-commands-telegram_admin_ids)). Empty or missing means nobody is an admin.
- `SLACK_WEBHOOK_URL` (optional): Slack Incoming Webhook URL that receives an alert for every new product. Leave it empty to disable the alerts; the API behaves exactly as before.

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

## Telegram bot

The bot answers catalog questions in Telegram with the same assistant as `POST /api/v1/catalog/ask`. It uses a webhook: Telegram sends every message to `POST /telegram/webhook`, and the API replies through the Bot API `sendMessage` method.

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot` and follow the steps. It gives you the bot token (`123456789:AA...`). Keep it secret: anyone with it controls the bot.
2. Generate a random webhook secret (1-256 characters, only `A-Z a-z 0-9 _ -`):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

3. Add both values to Render -> Environment (and to `.env` for local runs), then redeploy:
   - `TELEGRAM_BOT_TOKEN`: the BotFather token.
   - `TELEGRAM_WEBHOOK_SECRET`: the random secret.
4. Register the webhook once (replace `<TOKEN>`, `<render-host>` and `<secret>`):

   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     --data-urlencode "url=https://<render-host>/telegram/webhook" \
     --data-urlencode "secret_token=<secret>"
   ```

   Telegram then sends the secret in the `X-Telegram-Bot-Api-Secret-Token` header of every update, and the API rejects requests without it (`401`).
5. Check the webhook status, including the last delivery error:

   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
   ```

6. Open your bot in Telegram and send `/start`, then a question such as `¿Tienen teclados por menos de 100?`.

Behavior:

- `/start`, `/help` and `/ayuda` reply with usage instructions. Admins also see the admin commands; everyone else does not.
- `/productos` lists the products as `#id Name: price · N en stock` (`agotado` when out of stock), ordered by id, without calling Gemini. A long list is cut to fit Telegram's 4096-character limit and ends with `… y N más.`.
- `/id` replies with your Telegram user id. Anyone can use it.
- Any other command (including `/agregar` and `/editar` for now) replies that it is unknown or not available yet.
- Any other text is a catalog question, with the same limits as the API (1-500 characters). Answers are plain text.
- The webhook acknowledges at once and sends the answer from a background task, so Telegram does not redeliver the update while Gemini is thinking.
- Duplicate deliveries are ignored: the API remembers the last 1000 `update_id` values and acknowledges a repeated one without replying again. Limitation: this record lives in memory, so it is cleared when the service restarts or sleeps (Render free tier). It covers the common case, a redelivery within the same process lifetime, not every case.
- The bot's fixed messages (welcome, errors) are in Spanish. Gemini answers in the language of the question.
- Edited messages, stickers, photos and other updates are ignored.
- If Gemini is rate-limited or failing, the bot replies with a short "try again" message.
- If `TELEGRAM_BOT_TOKEN` or `TELEGRAM_WEBHOOK_SECRET` is missing, the webhook returns `503` and the rest of the API keeps working.
- Render's free tier sleeps after 15 minutes without traffic. The first message after that wakes the server, so its reply can take about a minute.
- If you rotate the token or the secret, update Render and run `setWebhook` again.

### Admin commands (`TELEGRAM_ADMIN_IDS`)

`TELEGRAM_ADMIN_IDS` is a comma-separated list of Telegram **user** ids, for example `123456789,987654321`. Only those users can run admin commands.

1. Open your bot and send `/id`. It replies with your user id.
2. Put it in `TELEGRAM_ADMIN_IDS` in Render -> Environment (and in `.env` for local runs), then redeploy.
3. Send `/ayuda`: the admin commands now appear in the help text.

Rules:

- The list holds **sender** ids (the author of a message), never chat ids. In a group, only the listed users are admins; the group's own id gives nobody any rights.
- It fails closed: if the variable is empty or missing, nobody is an admin. Spaces and empty items are ignored, and items that are not positive integers are ignored too.
- Admin commands are documented in `/ayuda` (`/agregar` and `/editar`). Both are implemented in a later change; until then the bot answers that they are not available.

## Slack alerts

Every successful `POST /api/v1/products` (`201`) can post a message to a Slack channel, for example `New product: Mechanical Keyboard (id 7) - price 49.50, stock 12`.

1. In Slack, create an app at <https://api.slack.com/apps> -> **Incoming Webhooks** -> activate it -> **Add New Webhook to Workspace**, and pick the channel.
2. Copy the webhook URL (`https://hooks.slack.com/services/...`) into Render -> Environment (and into `.env` for local runs) as `SLACK_WEBHOOK_URL`, then redeploy.

Behavior:

- Optional: with `SLACK_WEBHOOK_URL` empty or missing, nothing is sent and the API is unchanged.
- Failure-safe: the message is sent from a background task after the response, with a 3 second timeout and no retries. A Slack error, timeout or non-2xx answer is logged as a warning and never changes the `201` response. Invalid requests (`422`) send nothing.
- The product name is user-submitted, so `&`, `<` and `>` are escaped (no `@channel` mentions or links can be injected), newlines are collapsed and names over 100 characters are cut.
- The webhook URL is a secret: anyone who has it can post to your channel. Never commit it or paste it in issues or logs; the API never logs it. If it leaks, revoke it in the Slack app settings and create a new one.

## Deploy to Render

Create a **Web Service** from the GitHub repository that contains this folder:

| Setting           | Value                                              |
| ----------------- | -------------------------------------------------- |
| Root Directory    | `backend` (leave empty if `backend/` itself is the repo root) |
| Build Command     | `pip install -r requirements.txt`                  |
| Start Command     | `uvicorn main:app --host 0.0.0.0 --port $PORT`     |
| Health Check Path | `/health`                                          |
| Environment vars  | `DATABASE_URL`, `ALLOWED_ORIGINS`, `GEMINI_API_KEY`, optional `GEMINI_MODEL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, optional `TELEGRAM_ADMIN_IDS`, optional `SLACK_WEBHOOK_URL` (same as `.env`) |

Render reads `.python-version` to use Python 3.13.
