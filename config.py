"""
config.py — Central configuration for the Invoice Manager app.
"""

from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

# ── Secrets ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
DRIVE_FOLDER_ID: str = os.getenv("DRIVE_FOLDER_ID", "")
CREDENTIALS_PATH: str = os.getenv("CREDENTIALS_PATH", "credentials.json")
GEMINI_MODEL: str = "gemini-2.0-flash"
APP_PASSWORD: str = os.getenv("APP_PASSWORD", "")  # Leave empty for local use

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
    "כבוד קל ללקוחות",
    "קפה וחד פעמי",
    "משפטיות",
    "הוצאות לעורך דין",
    "משרדיות",
    "ציוד משרדי",
    "נסיעות",
    "תחבורה ציבורית",
    "מוניות",
    "ספרות מקצועית",
    "עמלות אשראי",
    "פרסום",
    "פייסבוק וגוגל",
    "רשתות חברתיות",
    "רכב - הוצאות משתנות",
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
    "הלוואות",
    "עמלות בנק",
]

# Fixed assets → append "רכוש קבוע" to filename
FIXED_ASSETS: list[str] = [
    "רכוש קבוע",
    "רכב",
    "מחשב",
    "מדפסת",
    "מסך",
    "טלפון נייד",
    "בניית אתר אינטרנט",
]

# Combined list for the Gemini prompt
ALL_EXPENSES: list[str] = MONTHLY_EXPENSES + ANNUAL_EXPENSES + FIXED_ASSETS
ANNUAL_EXPENSES_SET: set[str] = set(ANNUAL_EXPENSES)
FIXED_ASSETS_SET: set[str] = set(FIXED_ASSETS)
