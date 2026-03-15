"""
setup_auth.py — One-time OAuth2 authorisation for headless / WSL environments.

Run this ONCE from the terminal to generate token.json:
    uv run python setup_auth.py

WSL users: the script prints a URL — open it in your Windows browser.
The redirect (localhost:8088) comes back to WSL automatically.
After that, app.py will use token.json without any browser interaction.
"""

from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "credentials.json")
TOKEN_PATH = "token.json"

# Import scopes from config (covers Drive + Gmail)
from config import GOOGLE_SCOPES as SCOPES
PORT = 8088


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    print("=" * 60)
    print("  מנהל קבלות — הגדרת OAuth2 (פעם אחת בלבד)")
    print("=" * 60)
    print()

    if not os.path.exists(CREDENTIALS_PATH):
        print(f"❌  קובץ '{CREDENTIALS_PATH}' לא נמצא.")
        print("    הורד OAuth2 Desktop credentials מ-Google Cloud Console")
        print("    ושמור כ-credentials.json בתיקיית הפרויקט.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)

    print(f"🌐  מפעיל שרת מקומי על פורט {PORT}...")
    print()
    print("    ➡️  הסקריפט ידפיס קישור — פתח אותו ב-Windows browser")
    print("    ✅  לאחר האישור, הטוקן ייחשמר אוטומטית")
    print()

    # run_local_server starts a redirect listener and prints the URL.
    # open_browser=False prevents the (failing) xdg-open attempt.
    # WSL2 shares localhost with Windows, so the redirect works automatically.
    creds = flow.run_local_server(
        port=PORT,
        open_browser=False,
        success_message=(
            "✅ האישור הושלם! ניתן לסגור את הלשונית ולחזור לטרמינל."
        ),
    )

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    print()
    print(f"✅  token.json נשמר בהצלחה!")
    print("    עכשיו הרץ: uv run streamlit run app.py")


if __name__ == "__main__":
    main()
