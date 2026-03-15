"""
generate_secrets.py — Prints st.secrets values for Streamlit Cloud deployment.

Run locally ONCE after completing setup_auth.py:
    uv run python generate_secrets.py

Copy the output into your Streamlit Cloud app's Secrets page.
"""

from __future__ import annotations
import json
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")


def main() -> None:
    errors = []

    cred_path = os.getenv("CREDENTIALS_PATH", "credentials.json")
    token_path = "token.json"

    if not os.path.exists(cred_path):
        errors.append(f"❌ {cred_path} לא נמצא")
    if not os.path.exists(token_path):
        errors.append(f"❌ {token_path} לא נמצא — הרץ setup_auth.py קודם")

    if errors:
        for e in errors:
            print(e)
        return

    with open(cred_path) as f:
        credentials_json = json.dumps(json.load(f))

    with open(token_path) as f:
        token_json = json.dumps(json.load(f))

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    folder_id = os.getenv("DRIVE_FOLDER_ID", "")
    app_password = os.getenv("APP_PASSWORD", "")

    print("=" * 60)
    print("  העתק את הטקסט הבא ל-Streamlit Cloud → Secrets:")
    print("=" * 60)
    print()
    print(f'GEMINI_API_KEY = "{gemini_key}"')
    print(f'DRIVE_FOLDER_ID = "{folder_id}"')
    print(f'APP_PASSWORD = "{app_password}"')
    print(f'GOOGLE_CREDENTIALS = {repr(credentials_json)}')
    print(f'GOOGLE_TOKEN = {repr(token_json)}')
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
