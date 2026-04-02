# Sheets Search MCP

Make any Google Sheet queryable from Slack or any MCP client. Connect a spreadsheet, pick your LLM, customize the bot's persona, and let your team ask questions about the data.

Works in two modes:

- **Slack bot** — an AI assistant your team can DM or @mention in channels. Works with any LLM (OpenAI, Anthropic, Google, etc.)
- **MCP server** — tools for any MCP-compatible client (Claude Code, Cursor, etc.) to query, search, and filter spreadsheet data

## Prerequisites

Both modes need a Google service account to read the spreadsheet.

### 1. Create a Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project (or create one)
3. Enable the **Google Sheets API** (APIs & Services > Library)
4. Go to **IAM & Admin > Service Accounts**
5. Click **Create Service Account** — name it anything (e.g. "sheets-mcp")
6. Skip the optional permissions/access steps
7. Click the new service account > **Keys** tab > **Add Key > Create new key > JSON**
8. Save the downloaded file as `service-account.json` in this project root

### 2. Share the sheet with the service account

Copy the service account email (looks like `sheets-mcp@your-project.iam.gserviceaccount.com`) and share your Google Sheet with it (Viewer access is sufficient).

### 3. Install dependencies

```bash
uv sync
```

---

## Option A: Slack bot

### Configure environment

```bash
cp .env.example .env
```

Fill in:

- `SHEETS_SPREADSHEET_URL` — full URL of your Google Sheet
- `SLACK_BOT_TOKEN` — bot token (`xoxb-...`)
- `SLACK_APP_TOKEN` — app-level token for Socket Mode (`xapp-...`)
- An API key for your LLM provider (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)

### Pick a model

The bot uses [litellm](https://docs.litellm.ai/docs/providers) so it works with any LLM. Set the `MODEL` env var:

```bash
MODEL=anthropic/claude-haiku-4-5-20251001  # default
MODEL=openai/gpt-4o
MODEL=gemini/gemini-2.0-flash
```

### Customize the persona

Edit `FRAMING.md` to describe your data, define terminology, and set behavioral guidelines. The bot uses this as its system prompt. For cloud deploys, set the `BOT_FRAMING` env var instead.

### Run

```bash
uv run python -m sheets_search_mcp.bot
```

The bot works in DMs (via Slack's Assistant API) and in channels (via @mentions). It supports threaded conversations with context and follow-up question buttons.

### Deploy to Render

A `render.yaml` blueprint and `Dockerfile` are included. Set your env vars in the Render dashboard — use `GOOGLE_SERVICE_ACCOUNT_JSON` (raw JSON string) instead of a key file.

---

## Option B: MCP server

### Configure environment

Set the `SHEETS_SPREADSHEET_URL` env var to point to your Google Sheet, or add it to a `.env` file.

### Use with Claude Code

The `.mcp.json` is already configured. Restart Claude Code in this project directory and the tools will be available.

### Use with other MCP clients

Point your MCP client at the server:

```bash
uv run python -m sheets_search_mcp.server
```

### Available tools

- **get_sheet_schema** — view columns and sample data
- **query_sheet** — structured filters (column match, amount range, date range, sort)
- **search_sheet** — free-text search across all columns
- **refresh_data** — re-fetch data if the sheet was updated

---

## Configuration

See `.env.example` for all available options including model selection, framing path, and service account configuration.

## Security notes

- **Schema includes sample data.** The first 3 rows of each tab are sent to the LLM as part of the system prompt so it understands your data structure. Make sure those rows don't contain sensitive information.
- **Framing content is sent to the LLM.** Everything in `FRAMING.md` or `BOT_FRAMING` is included in every request. Don't put secrets or confidential information in there.
- **Spreadsheet URL is not validated.** Only use trusted Google Sheets URLs in `SHEETS_SPREADSHEET_URL`.
