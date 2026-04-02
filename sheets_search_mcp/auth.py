"""Service account authentication for Google Sheets API."""

import json
import os
from pathlib import Path

from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def get_credentials(credentials_path: str | None = None) -> Credentials:
    """Get service account credentials.

    Checks (in order):
    1. GOOGLE_SERVICE_ACCOUNT_JSON env var (raw JSON string, for cloud deploys)
    2. credentials_path argument or GOOGLE_SERVICE_ACCOUNT_PATH env var
    3. ./service-account.json in the project root
    """
    raw_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        info = json.loads(raw_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    if credentials_path is None:
        credentials_path = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_PATH",
            str(Path(__file__).parent.parent / "service-account.json"),
        )

    if not Path(credentials_path).exists():
        raise FileNotFoundError(
            f"Service account key not found at {credentials_path}. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON env var or create a key file at this path."
        )

    return Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
