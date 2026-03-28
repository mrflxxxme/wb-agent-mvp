"""
Test configuration — sets dummy env vars so Settings() doesn't raise
ValidationError at import time when no .env file is present.
Must be at the top of conftest.py before any src.* import.
"""
import os
import base64
import json

# Minimal valid values so pydantic-settings doesn't raise at collection time.
# Tests that actually call Settings properties use monkeypatch to override these.
_DUMMY_CREDS = base64.b64encode(json.dumps({
    "type": "service_account",
    "project_id": "test",
    "private_key_id": "key-id",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK\n-----END RSA PRIVATE KEY-----\n",
    "client_email": "test@test.iam.gserviceaccount.com",
    "client_id": "12345",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}).encode()).decode()

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:AABBCCtest")
os.environ.setdefault("TELEGRAM_ALLOWED_IDS", "233085299")
os.environ.setdefault("OWNER_CHAT_ID", "233085299")
os.environ.setdefault("SPREADSHEET_ID", "1DjfLItDaSZRJNMKId5mC_fJMpvDSPkcWeHD_Sy7RmTE")
os.environ.setdefault("GOOGLE_CREDENTIALS_JSON", _DUMMY_CREDS)
os.environ.setdefault("GEMINI_API_KEY", "AIzaSy_test_key_for_unit_tests")
