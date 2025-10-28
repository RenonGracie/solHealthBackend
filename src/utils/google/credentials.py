# src/utils/google/credentials.py
from __future__ import annotations

import os, json
from typing import Optional
from google.oauth2 import service_account

_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

_CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "google_credentials.json")

def _from_env() -> Optional[service_account.Credentials]:
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    b64 = os.environ.get("GOOGLE_CREDENTIALS_JSON_B64", "").strip()
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    if raw:
        try:
            info = json.loads(raw)
            return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        except Exception:
            pass

    if b64:
        import base64
        try:
            decoded = base64.b64decode(b64).decode("utf-8")
            info = json.loads(decoded)
            return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
        except Exception:
            pass

    if path and os.path.exists(path):
        return service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)

    return None

def get_credentials(subject_email: Optional[str] = None):
    """
    Env-first (GOOGLE_CREDENTIALS_JSON / _B64 / GOOGLE_APPLICATION_CREDENTIALS),
    then falls back to local google_credentials.json.
    """
    creds = _from_env()
    if not creds:
        if not os.path.exists(_CREDENTIALS_FILE):
            raise FileNotFoundError(
                f"Google credentials not found. Set env vars or place JSON at: {_CREDENTIALS_FILE}"
            )
        creds = service_account.Credentials.from_service_account_file(_CREDENTIALS_FILE, scopes=_SCOPES)

    if subject_email:
        creds = creds.with_subject(subject_email)
    return creds
