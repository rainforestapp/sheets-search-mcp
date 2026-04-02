# Sheets Search MCP

MCP server that makes a Google Sheet queryable from Claude.

## Setup

### 1. Create a Service Account

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

### 4. Use with Claude Code

The `.mcp.json` is already configured. Restart Claude Code in this project directory and the tools will be available:

- **get_sheet_schema** — view columns and sample data
- **query_spend** — structured filters (column match, amount range, date range, sort)
- **search_spend** — free-text search across all columns
- **refresh_data** — re-fetch data if the sheet was updated

## Configuration

Set `SHEETS_SPREADSHEET_URL` env var to point to a different sheet, or edit `server.py`.

Set `GOOGLE_SERVICE_ACCOUNT_PATH` env var to use a key file in a different location.
