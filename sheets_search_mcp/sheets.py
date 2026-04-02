"""Google Sheets client with query capabilities."""

import re
from datetime import datetime

import gspread

from .auth import get_credentials


class SheetsClient:
    def __init__(self, spreadsheet_url: str):
        self.spreadsheet_url = spreadsheet_url
        self._tabs: dict[str, TabData] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if not self._loaded:
            self.refresh()

    def refresh(self):
        """Fetch all data from the sheet."""
        creds = get_credentials()
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_url(self.spreadsheet_url)

        self._tabs = {}
        for ws in spreadsheet.worksheets():
            rows = ws.get_all_values()
            # Find header row: first row with 3+ non-empty cells
            header_idx = None
            for i, row in enumerate(rows):
                if len([c for c in row if c.strip()]) >= 3:
                    header_idx = i
                    break
            if header_idx is None:
                continue

            headers = rows[header_idx]
            # Deduplicate empty headers
            seen = {}
            clean_headers = []
            for h in headers:
                h = h.strip() or "unnamed"
                if h in seen:
                    seen[h] += 1
                    h = f"{h}_{seen[h]}"
                else:
                    seen[h] = 0
                clean_headers.append(h)

            data_rows = []
            for row in rows[header_idx + 1:]:
                if not any(c.strip() for c in row):
                    continue
                record = {clean_headers[j]: row[j] if j < len(row) else "" for j in range(len(clean_headers))}
                data_rows.append(record)

            self._tabs[ws.title] = TabData(ws.title, clean_headers, data_rows)

        self._loaded = True

    @property
    def tab_names(self) -> list[str]:
        self._ensure_loaded()
        return list(self._tabs.keys())

    def get_tab(self, name: str) -> "TabData | None":
        self._ensure_loaded()
        return self._tabs.get(name)

    # Convenience: default to first summary tab for backwards compat
    @property
    def headers(self) -> list[str]:
        self._ensure_loaded()
        first = next(iter(self._tabs.values()), None)
        return first.headers if first else []

    @property
    def rows(self) -> list[dict[str, str]]:
        self._ensure_loaded()
        first = next(iter(self._tabs.values()), None)
        return first.rows if first else []

    def get_schema(self) -> dict:
        """Return schema for all tabs."""
        self._ensure_loaded()
        tabs = {}
        for name, tab in self._tabs.items():
            tabs[name] = {
                "columns": tab.headers,
                "row_count": len(tab.rows),
                "sample_rows": tab.rows[:3],
            }
        return {"tabs": tabs}

    def search(self, query: str, limit: int = 50, tab: str | None = None) -> list[dict[str, str]]:
        """Free-text search across all columns."""
        self._ensure_loaded()
        tabs_to_search = [self._tabs[tab]] if tab and tab in self._tabs else self._tabs.values()
        query_lower = query.lower()
        results = []
        for t in tabs_to_search:
            for row in t.rows:
                if any(query_lower in v.lower() for v in row.values()):
                    tagged = dict(row)
                    tagged["_tab"] = t.name
                    results.append(tagged)
                    if len(results) >= limit:
                        return results
        return results

    def query(
        self,
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
    ) -> list[dict[str, str]]:
        """Structured query with filters, amount range, date range, and sorting."""
        self._ensure_loaded()

        if tab and tab in self._tabs:
            results = list(self._tabs[tab].rows)
        else:
            # Default to first tab
            first = next(iter(self._tabs.values()), None)
            results = list(first.rows) if first else []

        # Exact/substring column filters
        if filters:
            for col, value in filters.items():
                value_lower = value.lower()
                results = [
                    r for r in results
                    if col in r and value_lower in r[col].lower()
                ]

        # Amount range
        if amount_column and (min_amount is not None or max_amount is not None):
            filtered = []
            for r in results:
                try:
                    amt = float(re.sub(r"[,$]", "", r.get(amount_column, "")))
                except (ValueError, TypeError):
                    continue
                if min_amount is not None and amt < min_amount:
                    continue
                if max_amount is not None and amt > max_amount:
                    continue
                filtered.append(r)
            results = filtered

        # Date range
        if date_column and (date_from or date_to):
            filtered = []
            for r in results:
                raw = r.get(date_column, "")
                parsed = _try_parse_date(raw)
                if parsed is None:
                    continue
                if date_from and parsed < _try_parse_date(date_from):
                    continue
                if date_to and parsed > _try_parse_date(date_to):
                    continue
                filtered.append(r)
            results = filtered

        # Sort
        if sort_by:
            results.sort(key=lambda r: _sort_key(r.get(sort_by, "")), reverse=sort_desc)

        return results[:limit]


class TabData:
    def __init__(self, name: str, headers: list[str], rows: list[dict[str, str]]):
        self.name = name
        self.headers = headers
        self.rows = rows


def _try_parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _sort_key(value: str):
    """Try numeric sort first, fall back to string."""
    try:
        return (0, float(re.sub(r"[,$]", "", value)))
    except (ValueError, TypeError):
        return (1, value.lower())
