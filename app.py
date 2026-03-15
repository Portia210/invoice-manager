"""
app.py — Streamlit UI for the Invoice Manager.
"""

from __future__ import annotations
import logging
import os
from datetime import date

import streamlit as st

from config import DRIVE_FOLDER_ID, CREDENTIALS_PATH, GEMINI_API_KEY
from config import APP_PASSWORD
from drive_service import get_drive_service
from file_processor import process_file, MIME_TYPES

# ── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)

# ── Page Config ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="מנהל קבלות",
    page_icon="🧾",
    layout="centered",
)

# ── RTL styling ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        body, .stApp { direction: rtl; text-align: right; }
        .stTextInput, .stSelectbox, .stFileUploader { direction: rtl; }
        .result-card {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 12px 16px;
            margin: 8px 0;
            border-right: 4px solid #4CAF50;
        }
        .result-card.warning { border-right-color: #FF9800; background: #fff8e1; }
        .result-card.error   { border-right-color: #f44336; background: #fff5f5; }
        h1 { font-size: 2rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Configuration Check ─────────────────────────────────────────────────────────
def _check_config() -> list[str]:
    """Return a list of configuration error messages."""
    errors = []

    # Check secrets from st.secrets (cloud) or env vars (local)
    try:
        gemini_key = st.secrets.get("GEMINI_API_KEY", GEMINI_API_KEY)
        folder_id = st.secrets.get("DRIVE_FOLDER_ID", DRIVE_FOLDER_ID)
        has_creds = (
            "GOOGLE_CREDENTIALS" in st.secrets
            or os.path.exists(CREDENTIALS_PATH)
        )
    except Exception:
        gemini_key = GEMINI_API_KEY
        folder_id = DRIVE_FOLDER_ID
        has_creds = os.path.exists(CREDENTIALS_PATH)

    if not gemini_key:
        errors.append("❌ `GEMINI_API_KEY` חסר")
    if not folder_id:
        errors.append("❌ `DRIVE_FOLDER_ID` חסר")
    if not has_creds:
        errors.append(f"❌ קובץ הרשאות Google לא נמצא: `{CREDENTIALS_PATH}`")
    return errors


# ── Password Gate ───────────────────────────────────────────────────────────────
_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 60

def _require_password() -> bool:
    """
    Password gate with brute-force protection.
    Returns True if authenticated (or no password configured).
    """
    import hmac
    import time

    # No password → open (warn on cloud)
    if not APP_PASSWORD:
        if os.getenv("STREAMLIT_SHARING_MODE"):  # running on Streamlit Cloud
            st.warning("⚠️ `APP_PASSWORD` לא הוגדר — האפליקציה פתוחה לכולם!")
        return True

    if st.session_state.get("authenticated"):
        return True

    # Brute-force protection
    attempts = st.session_state.get("login_attempts", 0)
    lockout_until = st.session_state.get("lockout_until", 0)

    if time.time() < lockout_until:
        remaining = int(lockout_until - time.time())
        st.error(f"🔒 יותר מדי ניסיונות. נסה שוב בעוד {remaining} שניות.")
        return False

    st.markdown(
        """
        <div style='max-width:340px; margin:8vh auto; text-align:center'>
            <div style='font-size:3rem'>🧾</div>
            <h2 style='margin-bottom:0.2em'>מנהל קבלות</h2>
            <p style='color:#666; margin-bottom:1.5em'>הכנס סיסמה להמשך</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("login", clear_on_submit=True):
        pwd = st.text_input("סיסמה", type="password", label_visibility="collapsed",
                            placeholder="הכנס סיסמה...")
        submitted = st.form_submit_button("כניסה", use_container_width=True, type="primary")

    if submitted:
        if hmac.compare_digest(pwd, APP_PASSWORD):
            st.session_state["authenticated"] = True
            st.session_state["login_attempts"] = 0
            st.rerun()
        else:
            attempts += 1
            st.session_state["login_attempts"] = attempts
            remaining = _MAX_ATTEMPTS - attempts
            if remaining > 0:
                st.error(f"❌ סיסמה שגויה ({remaining} ניסיונות נותרו)")
            else:
                st.session_state["lockout_until"] = time.time() + _LOCKOUT_SECONDS
                st.session_state["login_attempts"] = 0
                st.error(f"🔒 נעילה זמנית ל-{_LOCKOUT_SECONDS} שניות")

    return False


def main() -> None:
    st.title("🧾 מנהל קבלות חכם")
    st.markdown(
        "העלה קבלות וחשבוניות — המערכת תסווג אותן אוטומטית ותעלה ל-Google Drive "
        "לתיקייה הנכונה, בשמות מסודרים.",
    )
    st.divider()

    # Config warnings in sidebar
    config_errors = _check_config()
    with st.sidebar:
        st.header("⚙️ הגדרות")
        if config_errors:
            for err in config_errors:
                st.error(err)
        else:
            st.success("✅ כל ההגדרות תקינות")

        st.markdown("---")
        st.markdown("**תיקיית בסיס ב-Drive:**")
        st.code(DRIVE_FOLDER_ID or "לא הוגדר", language=None)
        st.markdown("**קובץ הרשאות:**")
        st.code(CREDENTIALS_PATH, language=None)
        st.markdown("---")
        st.markdown("**סוגי קבצים נתמכים:**  \n"
            + ", ".join(f"`{ext}`" for ext in MIME_TYPES))

        st.markdown("---")
        st.markdown("### 🔑 סוג הרשאות")

        # Detect credential type
        cred_type = "לא ידוע"
        try:
            import json as _json
            with open(CREDENTIALS_PATH) as f:
                _cred = _json.load(f)
            if _cred.get("type") == "service_account":
                cred_type = "🏢 Service Account (צריך Shared Drive)"
            elif "installed" in _cred or "web" in _cred:
                cred_type = "👤 OAuth2 — Gmail אישי ✅"
        except Exception:
            pass

        st.info(f"**סוג:** {cred_type}")

        with st.expander("📋 הגדרת OAuth2 לחשבון Gmail אישי", expanded=False):
            st.markdown(
                "אם יש לך חשבון Gmail אישי (לא Workspace), השתמש ב-OAuth2:\n\n"
                "1. פתח [console.cloud.google.com](https://console.cloud.google.com)\n"
                "2. APIs & Services → **Credentials** → **+ Create Credentials** → **OAuth client ID**\n"
                "3. Application type: **Desktop app**\n"
                "4. לחץ **Download JSON** → שמור כ-`credentials.json` בתיקיית הפרויקט\n"
                "5. בהרצה הראשונה יפתח דפדפן לאישור → אשר גישה\n"
                "6. הטוקן נשמר אוטומטית ב-`token.json` לשימוש עתידי\n\n"
                "**תיקיית Drive:** צור תיקייה רגילה ב-My Drive → העתק ID מה-URL"
            )

    if config_errors:
        st.error("יש לתקן את שגיאות ההגדרה בסרגל הצדדי לפני השימוש.")
        st.stop()


    # File uploader
    uploaded_files = st.file_uploader(
        "📎 גרור קבלות לכאן או לחץ לבחירת קבצים",
        type=[ext.lstrip(".") for ext in MIME_TYPES],
        accept_multiple_files=True,
        help="ניתן לבחור מספר קבצים בו-זמנית",
    )

    if not uploaded_files:
        st.info("ממתין לקבצים... העלה קבלה כדי להתחיל.")
        return

    if st.button("🚀 עבד קבלות", type="primary", use_container_width=True):
        _run_processing(uploaded_files)


def _run_processing(uploaded_files: list) -> None:
    """Process all uploaded files and display results."""
    st.divider()
    st.subheader(f"📊 מעבד {len(uploaded_files)} קובץ/ים...")

    # Initialise Drive service once
    with st.spinner("מתחבר ל-Google Drive..."):
        try:
            service = get_drive_service()
        except Exception as exc:
            st.error(f"❌ שגיאה בחיבור ל-Google Drive: {exc}")
            return

    results = []
    progress_bar = st.progress(0, text="מתחיל עיבוד...")
    total = len(uploaded_files)

    for idx, uploaded_file in enumerate(uploaded_files):
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name

        progress_bar.progress(
            (idx) / total,
            text=f"מעבד ({idx + 1}/{total}): {filename}",
        )

        with st.spinner(f"🔍 מנתח: {filename}"):
            result = process_file(
                file_bytes=file_bytes,
                original_filename=filename,
                service=service,
                root_folder_id=DRIVE_FOLDER_ID,
            )

        results.append(result)

        # Per-file feedback
        if result.status == "success":
            st.success(f"✅ **{filename}** → `{result.new_filename}`  \n📁 {result.target_folder}")
        elif result.status == "duplicate":
            st.warning(f"⚠️ **{filename}** — קובץ כפול, דולג.")
        else:
            st.error(f"❌ **{filename}** — {result.message}")

    progress_bar.progress(1.0, text="✅ עיבוד הושלם!")

    # Summary table
    st.divider()
    st.subheader("📋 סיכום")

    success_count = sum(1 for r in results if r.status == "success")
    dup_count = sum(1 for r in results if r.status == "duplicate")
    error_count = sum(1 for r in results if r.status == "error")

    col1, col2, col3 = st.columns(3)
    col1.metric("✅ הועלו בהצלחה", success_count)
    col2.metric("⚠️ כפולים שדולגו", dup_count)
    col3.metric("❌ שגיאות", error_count)

    # Detailed results
    if any(r.status == "success" for r in results):
        st.markdown("### קישורים לקבצים שהועלו")
        for r in results:
            if r.status == "success":
                ai = r.ai_data
                amount = ai.get("total_amount")
                amount_str = f" | **סכום:** ₪{amount:,.2f}" if amount else ""
                link_md = f"[פתח ב-Drive]({r.drive_link})" if r.drive_link else ""
                st.markdown(
                    f"- 📄 `{r.new_filename}`  \n"
                    f"  📁 `{r.target_folder}` | "
                    f"**סוג:** {ai.get('expense_type', '')} | "
                    f"**ספק:** {ai.get('provider', '')}"
                    f"{amount_str}  \n"
                    f"  {link_md}"
                )



if __name__ == "__main__":
    if _require_password():
        main()
