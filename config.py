"""
config.py — Central configuration for the Invoice Manager app.
"""

from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

# ── Secrets ─────────────────────────────────────────────────────────────────────
# Prefer st.secrets (Streamlit Cloud) → fall back to .env (local)
def _get_secret(key: str, default: str = "") -> str:
    try:
        import streamlit as st
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)

GEMINI_API_KEY: str = _get_secret("GEMINI_API_KEY")
DRIVE_FOLDER_ID: str = _get_secret("DRIVE_FOLDER_ID")
CREDENTIALS_PATH: str = _get_secret("CREDENTIALS_PATH", "credentials.json")
GEMINI_MODEL: str = "gemini-2.0-flash"
APP_PASSWORD: str = _get_secret("APP_PASSWORD")
REQUIRE_PASSWORD: bool = _get_secret("REQUIRE_PASSWORD", "TRUE").upper() != "FALSE"

# ── OAuth Scopes ─────────────────────────────────────────────────────────────────
GOOGLE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# ── Hebrew Calendar ─────────────────────────────────────────────────────────────
HEBREW_MONTHS: dict[int, str] = {
    1: "ינואר",
    2: "פברואר",
    3: "מרץ",
    4: "אפריל",
    5: "מאי",
    6: "יוני",
    7: "יולי",
    8: "אוגוסט",
    9: "ספטמבר",
    10: "אוקטובר",
    11: "נובמבר",
    12: "דצמבר",
}

METADATA_FILENAME = "metadata.json"
FIXED_ASSET_SUFFIX = "רכוש קבוע"
ANNUAL_FOLDER_SUFFIX = "שנתי"
NON_BUSINESS_FOLDER_NAME = "NON BUSINESS"

# ── Expense Categories ──────────────────────────────────────────────────────────
# Monthly / regular operating expenses
MONTHLY_EXPENSES: list[str] = [
    "הוצאות ישירות לעסק",
    "קניות",
    "אחזקת משרד",
    "חדר עבודה",
    "אחזקת מחשב",
    "אתר אינטרנט",
    "ארנונה",
    "מים וחשמל",
    "אימון עסקי",
    "קאוצ'ינג",
    "דואר",
    "שליחויות",
    "הובלות",
    "השתלמויות",
    "ייעוץ מקצועי",
    "יחסי ציבור",
    "כיבוד קל", # coffee, cookies, etc (no meals)
    "משפטיות",
    "משרדיות",
    "ציוד משרדי",
    "הוצאות רכב",
    "תחבורה ציבורית",
    "מוניות",
    "ספרות מקצועית",
    "עמלות אשראי",
    "פרסום",
    "פייסבוק וגוגל",
    "רשתות חברתיות",
    "דלק",
    "חשמל לרכב",
    "חניה",
    "כביש 6",
    "ליסינג",
    "תיקוני רכב",
    "שירותי כח אדם",
    "תשלום לפרילנס",
    "שכר דירה עסקי",
    "שכר טרחת רואה חשבון",
    "ייעוץ מס",
    "תקשורת",
    "אינטרנט",
    "טלפון",
    "פלאפון",
    "תוכנות מקצועיות",
]

# Annual / once-a-year expenses → go to YYYY שנתי folder
ANNUAL_EXPENSES: list[str] = [
    "חובה רכב",
    "טסט רכב",
    "ביטוח מקיף",
    "ביטוח משרד",
    "ביטוח אחריות מקצועית",
    "הוצאות ריבית",
    "הלוואות לעסק",
]

# Fixed assets → append "רכוש קבוע" to filename
FIXED_ASSETS: list[str] = [
    "רכוש קבוע",
    "רכב קניה",
    "מחשב קניה",
    "מדפסת קניה",
    "מסך קניה",
    "טלפון קניה",
    "בניית אתר אינטרנט",
]

# Combined list for the Gemini prompt
ALL_EXPENSES: list[str] = MONTHLY_EXPENSES + ANNUAL_EXPENSES + FIXED_ASSETS
ANNUAL_EXPENSES_SET: set[str] = set(ANNUAL_EXPENSES)
FIXED_ASSETS_SET: set[str] = set(FIXED_ASSETS)
