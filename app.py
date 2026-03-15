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
from gmail_service import get_gmail_service
from gmail_scanner import scan_gmail_for_receipts

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
        if hmac.compare_digest(pwd.encode("utf-8"), APP_PASSWORD.encode("utf-8")):
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


logger = logging.getLogger(__name__)

# Silence noisy background libraries
logging.getLogger("fontTools").setLevel(logging.WARNING)
logging.getLogger("weasyprint").setLevel(logging.WARNING)
logging.getLogger("playwright").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)

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

    # Initialise Drive service once (shared across tabs)
    if "drive_service" not in st.session_state:
        with st.spinner("מתחבר ל-Google Drive..."):
            try:
                st.session_state["drive_service"] = get_drive_service()
            except Exception as exc:
                st.error(f"❌ שגיאה בחיבור ל-Google Drive: {exc}")
                return
    service = st.session_state["drive_service"]

    # ── Two action tabs ─────────────────────────────────────────────────────────
    tab_upload, tab_gmail, tab_history = st.tabs(["📎 העלאת קבצים", "📧 ייבא מהמייל", "📜 היסטוריה"])

    with tab_upload:
        _upload_tab(service)

    with tab_gmail:
        _gmail_tab(service)

    with tab_history:
        _history_tab(service)


def _upload_tab(service) -> None:
    """Manual file upload tab."""
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
        _run_processing(uploaded_files, service)


def _gmail_tab(service) -> None:
    """Gmail scanner tab."""
    st.markdown(
        "סריקת תיבת הדואר הנכנס לשנה האחרונה — איתור קבלות אוטומטי.  \n"
        "מיילים שנסרקו כבר לא יוצגו שוב בסריקות הבאות."
    )

    if st.button("📧 ייבא קבלות מהמייל", type="primary", use_container_width=True, key="gmail_scan"):
        _run_gmail_scan(service)


def _run_gmail_scan(drive_service) -> None:
    """Run Gmail scan and display results with structured grouping."""
    st.divider()
    
    # Live logging container
    log_container = st.status("🔍 מתחיל סריקת Gmail...", expanded=True)
    progress_bar = st.progress(0)

    try:
        gmail_svc = get_gmail_service()
    except Exception as exc:
        st.error(f"❌ שגיאה בחיבור ל-Gmail: {exc}")
        return

    def progress_cb(current: int, total: int, text: str) -> None:
        frac = (current / total) if total > 0 else 0
        progress_label = f"סורק מיילים... ({current + 1}/{total})"
        progress_bar.progress(frac, text=progress_label)
        
        # Only log significant events to the status container to keep it clean
        if "**" in text or "✅" in text or "❌" in text:
            log_container.write(f"• {text}")

    try:
        results = scan_gmail_for_receipts(
            drive_service=drive_service,
            gmail_service=gmail_svc,
            root_folder_id=DRIVE_FOLDER_ID,
            progress_cb=progress_cb,
        )
    except Exception as exc:
        st.error(f"❌ שגיאת סריקה: {exc}")
        log_container.update(label="❌ הסריקה נכשלה", state="error")
        return

    log_container.update(label="✅ הסריקה הושלמה", state="complete", expanded=False)
    progress_bar.empty()

    if not results:
        st.success("✅ אין מיילים חדשים לעיבוד.")
        return

    # Categorize results
    success_list = [r for r in results if r.process_result and r.process_result.status == "success"]
    skip_list = [r for r in results if r.skipped or (r.process_result and r.process_result.status == "duplicate")]
    error_list = [r for r in results if r.error or (r.process_result and r.process_result.status == "error")]

    # Summary metrics
    st.subheader("📊 סיכום סריקה")
    c1, c2, c3 = st.columns(3)
    c1.metric("✅ הועלו", len(success_list))
    c2.metric("⏭️ דולגו", len(skip_list))
    c3.metric("❌ שגיאות", len(error_list))

    # Detailed results with expanders for clarity
    if success_list:
        with st.expander("✅ קבלות חדשות שהועלו", expanded=True):
            for r in success_list:
                pr = r.process_result
                biz = "🏢" if pr.is_business else "👤"
                st.markdown(
                    f"**{biz} {pr.new_filename}**  \n"
                    f"📂 תיקייה: `{pr.target_folder}` | [פתח ב-Drive]({pr.drive_link})"
                )

    if skip_list:
        with st.expander("⏭️ מיילים שדולגו / כפולים", expanded=False):
            for r in skip_list:
                subject = r.subject[:60] or "(ללא נושא)"
                if r.skipped:
                    reason_map = {
                        "low_score": "סבירות נמוכה (לא נראה כמו קבלה)",
                        "zero_amount": "סכום 0 או ניסיון חינם",
                        "exclusion_list": "מייל שיווקי או פרסומי",
                    }
                    reason_text = reason_map.get(r.skip_reason, "לא נמצאה קבלה")
                    st.write(f"• **{subject}** — {reason_text}")
                else:
                    st.write(f"• **{subject}** — קובץ כפול ב-Drive")

    if error_list:
        with st.expander("❌ שגיאות ובעיות", expanded=True):
            for r in error_list:
                subject = r.subject[:60] or "(ללא נושא)"
                err_msg = r.error or (r.process_result.message if r.process_result else "שגיאה לא ידועה")
                st.error(f"**{subject}** — {err_msg}")


def _run_processing(uploaded_files: list, service) -> None:
    """Process all uploaded files with structured UI feedback."""
    st.divider()
    
    log_container = st.status(f"📊 מעבד {len(uploaded_files)} קובץ/ים...", expanded=True)
    progress_bar = st.progress(0)
    
    results = []
    total = len(uploaded_files)

    for idx, uploaded_file in enumerate(uploaded_files):
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name

        progress_bar.progress(idx / total)
        log_container.write(f"• מעבד: **{filename}**")

        result = process_file(
            file_bytes=file_bytes,
            original_filename=filename,
            service=service,
            root_folder_id=DRIVE_FOLDER_ID,
        )
        results.append(result)

    progress_bar.empty()
    log_container.update(label="✅ עיבוד הקבצים הושלם", state="complete", expanded=False)

    # ── Grouped Results ───────────────────────────────────────────────────────
    success_list = [r for r in results if r.status == "success"]
    dupe_list = [r for r in results if r.status == "duplicate"]
    error_list = [r for r in results if r.status == "error"]

    c1, c2, c3 = st.columns(3)
    c1.metric("✅ הועלו", len(success_list))
    c2.metric("⚠️ כפולים", len(dupe_list))
    c3.metric("❌ שגיאות", len(error_list))

    if success_list:
        with st.expander("✅ הועלו בהצלחה", expanded=True):
            for r in success_list:
                st.markdown(f"**{r.new_filename}**  \n📁 {r.target_folder} — [פתח ב-Drive]({r.drive_link})")

    if dupe_list:
        with st.expander("⚠️ קבצים כפולים (דולגו)", expanded=False):
            for r in dupe_list:
                st.write(f"• **{r.original_filename}**")

    if error_list:
        with st.expander("❌ שגיאות", expanded=True):
            for r in error_list:
                st.error(f"**{r.original_filename}** — {r.message}")

def _history_tab(service) -> None:
    """Display history of processed receipts from metadata.json."""
    st.markdown("### 📜 קבלות שנוספו למערכת")
    st.info("כאן מופיע ריכוז של כל הקבלות שעובדו ונוספו ל-Google Drive.")

    from deduplication import load_metadata
    
    with st.spinner("טוען היסטוריה מה-Drive..."):
        try:
            metadata, _ = load_metadata(service, DRIVE_FOLDER_ID)
        except Exception as exc:
            st.error(f"❌ שגיאה בטעינת היסטוריה: {exc}")
            return

    hashes = metadata.get("hashes", {})
    if not hashes:
        st.info("טרם עובדו קבלות.")
        return

    # Convert to list for display
    history_data = []
    for h, data in hashes.items():
        history_data.append({
            "תאריך": data.get("date", "לא ידוע"),
            "סכום": f"{data.get('amount', 0):,.2f}" if data.get('amount') else "-",
            "ספק": data.get("provider", "לא ידוע"),
            "סוג": data.get("expense_type", "לא ידוע"),
            "מקור": data.get("original_filename", h[:8]),
            "קישור": data.get("drive_link", ""),
        })

    # Sort by date descending
    history_data.sort(key=lambda x: x["תאריך"], reverse=True)

    import pandas as pd
    df = pd.DataFrame(history_data)
    
    # ── Filter UI ──────────────────────────────────────────────────────────────
    c1, c2 = st.columns([2, 1])
    search = c1.text_input("🔍 חיפוש לפי ספק או סוג:", help="חפש בהיסטוריה המקומית")
    sort_on = c2.selectbox("מיין לפי:", ["תאריך ↓", "תאריך ↑", "סכום ↓", "ספק"], index=0)

    if search:
        df = df[df["ספק"].str.contains(search, case=False, na=False) | 
                df["סוג"].str.contains(search, case=False, na=False) |
                df["מקור"].str.contains(search, case=False, na=False)]

    if sort_on == "תאריך ↓":
        df = df.sort_values("תאריך", ascending=False)
    elif sort_on == "תאריך ↑":
        df = df.sort_values("תאריך", ascending=True)
    elif sort_on == "סכום ↓":
        # Temporary numeric column for sorting
        df["_amt"] = df["סכום"].str.replace(",", "").replace("-", "0").astype(float)
        df = df.sort_values("_amt", ascending=False).drop(columns=["_amt"])
    elif sort_on == "ספק":
        df = df.sort_values("ספק")

    st.dataframe(
        df,
        column_config={
            "קישור": st.column_config.LinkColumn("📂 פתח ב-Drive", width="medium"),
            "סכום": st.column_config.TextColumn("💰 סכום", width="small"),
            "תאריך": st.column_config.DateColumn("📅 תאריך", format="YYYY-MM-DD"),
            "ספק": st.column_config.TextColumn("🏢 ספק"),
            "סוג": st.column_config.TextColumn("🏷️ סוג"),
        },
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    if _require_password():
        main()
