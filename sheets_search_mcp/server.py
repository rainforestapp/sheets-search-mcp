"""MCP server for querying Google Sheets data."""

import json
import os

from mcp.server.fastmcp import FastMCP

from .sheets import SheetsClient

SPREADSHEET_URL = os.environ.get("SHEETS_SPREADSHEET_URL")
if not SPREADSHEET_URL:
    raise RuntimeError("SHEETS_SPREADSHEET_URL environment variable is required")

mcp = FastMCP("sheets-search")
client = SheetsClient(SPREADSHEET_URL)


@mcp.tool()
def get_sheet_schema() -> str:
    """Get all tabs with their column names, row counts, and sample rows.
    Call this first to understand the data structure before querying."""
    return json.dumps(client.get_schema(), indent=2)


@mcp.tool()
def query_sheet(
    tab: str | None = None,
    filters: dict[str, str] | None = None,
    amount_column: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    date_column: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str | None = None,
    sort_desc: bool = True,
    limit: int = 50,
) -> str:
    """Query spreadsheet data with structured filters.

    Args:
        tab: Tab name to query. Defaults to first tab.
        filters: Column name -> value substring match (e.g. {"Name": "Acme"})
        amount_column: Name of the column containing amounts to filter on
        min_amount: Minimum amount (inclusive)
        max_amount: Maximum amount (inclusive)
        date_column: Name of the column containing dates to filter on
        date_from: Start date (YYYY-MM-DD)
        date_to: End date (YYYY-MM-DD)
        sort_by: Column name to sort by
        sort_desc: Sort descending (default True)
        limit: Max rows to return (default 50)
    """
    results = client.query(
        tab=tab,
        filters=filters,
        amount_column=amount_column,
        min_amount=min_amount,
        max_amount=max_amount,
        date_column=date_column,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_desc=sort_desc,
        limit=limit,
    )
    return json.dumps({"count": len(results), "rows": results}, indent=2)


@mcp.tool()
def search_sheet(query: str, tab: str | None = None, limit: int = 50) -> str:
    """Free-text search across all columns.

    Args:
        query: Text to search for (case-insensitive, matches any column)
        tab: Tab name to search in. Omit to search all tabs.
        limit: Max rows to return (default 50)
    """
    results = client.search(query, tab=tab, limit=limit)
    return json.dumps({"count": len(results), "rows": results}, indent=2)


@mcp.tool()
def refresh_data() -> str:
    """Re-fetch data from Google Sheets. Use if the sheet has been updated."""
    client.refresh()
    tab_counts = {name: len(client.get_tab(name).rows) for name in client.tab_names}
    return json.dumps({"status": "ok", "tabs": tab_counts})


if __name__ == "__main__":
    mcp.run(transport="stdio")
