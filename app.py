"""
app.py — Streamlit UI for the Invoice Manager.
"""

from __future__ import annotations
import logging

# ── Centralized Logging ────────────────────────────────────────────────────────
import logger_setup

import os
from datetime import date

import streamlit as st

from config import DRIVE_FOLDER_ID, CREDENTIALS_PATH, GEMINI_API_KEY
from config import APP_PASSWORD
from drive_service import get_drive_service
from file_processor import process_file, MIME_TYPES
from gmail_service import get_gmail_service
from gmail_scanner import scan_gmail_for_receipts


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
    from config import REQUIRE_PASSWORD # Import here to ensure it's loaded

    # If REQUIRE_PASSWORD=FALSE in env, skip entirely
    if not REQUIRE_PASSWORD:
        return True

    # No password configured → open (warn on cloud)
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
        submitted = st.form_submit_button("כניסה", width="stretch", type="primary")

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

    # Authenticate once to ensure credentials exist
    try:
        get_drive_service()
    except Exception as exc:
        st.error(f"❌ שגיאה בחיבור ל-Drive: {exc}")
        return

    # ── Two action tabs ─────────────────────────────────────────────────────────
    tab_upload, tab_gmail, tab_history = st.tabs(["📎 העלאת קבצים", "📧 ייבא מהמייל", "📜 היסטוריה"])

    with tab_upload:
        _upload_tab()

    with tab_gmail:
        _gmail_tab()

    with tab_history:
        _history_tab()


def _upload_tab() -> None:
    """Manual file upload tab."""
    service = get_drive_service()
    uploaded_files = st.file_uploader(
        "📎 גרור קבלות לכאן או לחץ לבחירת קבצים",
        type=[ext.lstrip(".") for ext in MIME_TYPES],
        accept_multiple_files=True,
        help="ניתן לבחור מספר קבצים בו-זמנית",
    )

    if not uploaded_files:
        st.info("ממתין לקבצים... העלה קבלה כדי להתחיל.")
        return

    if st.button("🚀 עבד קבלות", type="primary", width="stretch"):
        _run_processing(uploaded_files, service)


def _gmail_tab() -> None:
    """Gmail scanner tab."""
    st.markdown(
        "סריקת תיבת הדואר הנכנס לשנה האחרונה — איתור קבלות אוטומטי.  \n"
        "מיילים שנסרקו כבר לא יוצגו שוב בסריקות הבאות."
    )

    if st.button("📧 ייבא קבלות מהמייל", type="primary", width="stretch", key="gmail_scan", disabled=st.session_state.get("scan_active", False)):
        # We don't clear results here anymore to allow resumption/accumulation.
        # User has the "נקה רשימה" button to reset.
        _run_gmail_scan()


def _run_gmail_scan() -> None:
    """Run Gmail scan and display results with structured grouping."""
    drive_service = get_drive_service()
    st.divider()
    
    # Initialize stop event in session state
    if "scan_stop_event" not in st.session_state:
        import threading
        st.session_state.scan_stop_event = threading.Event()
    
    st.session_state.scan_stop_event.clear()

    # Initialize session state for persistence
    if "gmail_results" not in st.session_state:
        st.session_state.gmail_results = []
    if "scan_active" not in st.session_state:
        st.session_state.scan_active = False

    # Show stop button if scanning
    col_status, col_stop = st.columns([4, 1])
    with col_stop:
        if st.button("🛑 עצור", type="secondary", use_container_width=True):
            st.session_state.scan_stop_event.set()
            st.warning("עוצר סריקה... אנא המתן לסיום התהליכים הנוכחיים.")

    with col_status:
        # Live logging container
        log_status = st.empty()
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
        
        # Distinction: general status vs important events
        if "🧠" in text:
            log_container.write(f"• {text}")
        elif "🔍" in text:
            log_status.text(text) # Fast changing status in small text
        elif "✅" in text or "❌" in text:
            log_container.write(f"• {text}")

    try:
        st.session_state.scan_active = True
        results = scan_gmail_for_receipts(
            root_folder_id=DRIVE_FOLDER_ID,
            progress_cb=progress_cb,
            stop_event=st.session_state.scan_stop_event,
        )
        st.session_state.gmail_results.extend(results)
    except Exception as exc:
        st.error(f"❌ שגיאת סריקה: {exc}")
        log_container.update(label="❌ הסריקה נכשלה", state="error")
        return
    finally:
        st.session_state.scan_active = False

    log_container.update(label="✅ הסריקה הושלמה", state="complete", expanded=False)
    progress_bar.empty()
    log_status.empty()

    # Categorize and display results
    _display_gmail_results(st.session_state.gmail_results)

def _display_gmail_results(results: list) -> None:
    """Display the cumulative results of Gmail scans."""
    if not results:
        return

    st.divider()
    c_head, c_clear = st.columns([4, 1])
    c_head.subheader("📊 תוצאות סריקה (מצטבר)")
    if c_clear.button("🗑️ נקה רשימה", use_container_width=True):
        st.session_state.gmail_results = []
        st.rerun()

    success_list = [r for r in results if r.process_result and r.process_result.status == "success"]
    skip_list = [r for r in results if r.skipped or (r.process_result and r.process_result.status in ["duplicate", "skipped"])]
    error_list = [r for r in results if r.error or (r.process_result and r.process_result.status == "error")]

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
                elif r.process_result and r.process_result.status == "skipped":
                    st.write(f"• **{subject}** — {r.process_result.message}")
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
    skip_list = [r for r in results if r.status in ["duplicate", "skipped"]]
    error_list = [r for r in results if r.status == "error"]

    c1, c2, c3 = st.columns(3)
    c1.metric("✅ הועלו", len(success_list))
    c2.metric("⚠️ דולגו", len(skip_list))
    c3.metric("❌ שגיאות", len(error_list))

    if success_list:
        with st.expander("✅ הועלו בהצלחה", expanded=True):
            for r in success_list:
                st.markdown(f"**{r.new_filename}**  \n📁 {r.target_folder} — [פתח ב-Drive]({r.drive_link})")

    if skip_list:
        with st.expander("⚠️ קבצים שדולגו (כפולים או לא קבלות)", expanded=False):
            for r in skip_list:
                reason = "כבר קיים" if r.status == "duplicate" else "לא מסמך כספי"
                st.write(f"• **{r.original_filename}** — {reason}")

    if error_list:
        with st.expander("❌ שגיאות", expanded=True):
            for r in error_list:
                st.error(f"**{r.original_filename}** — {r.message}")

def _history_tab() -> None:
    """Display history of processed receipts from metadata.json."""
    service = get_drive_service()
    st.markdown("### 📜 קבלות שנוספו למערכת")
    
    c_title, c_refresh = st.columns([4, 1])
    with c_refresh:
        if st.button("🔄 רענן", icon="🔄", use_container_width=True, key="history_top_refresh"):
            st.rerun()

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
        st.info("📭 טרם עובדו קבלות. לאחר שתפעיל את הסורק או תעלה קבצים, הם יופיעו כאן.")
        if st.button("🔄 רענן היסטוריה", width="stretch"):
            st.rerun()
        return

    # Convert to list for display
    history_data = []
    total_amount = 0.0
    business_count = 0
    
    for h, data in hashes.items():
        amt = data.get('amount', 0)
        is_biz = data.get("is_business", True)
        
        history_data.append({
            "תאריך": data.get("date", "לא ידוע"),
            "סכום_נומרי": float(amt) if amt else 0.0,
            "סכום": f"{amt:,.2f}" if amt else "-",
            "ספק": data.get("provider", "לא ידוע"),
            "סוג": data.get("expense_type", "לא ידוע"),
            "מקור": data.get("original_filename", h[:8]),
            "קישור": data.get("drive_link", ""),
            "עסקי": "✅ עסקי" if is_biz else "👤 פרטי",
        })
        
        if amt:
            total_amount += float(amt)
        if is_biz:
            business_count += 1
            
    # ── Summary Metrics ───────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("💰 סה\"כ הוצאות", f"₪{total_amount:,.2f}")
    m2.metric("📄 מספר קבלות", len(history_data))
    m3.metric("🏢 הוצאות עסק", f"{business_count}/{len(history_data)}")
    
    st.divider()

    # Sort by date descending
    history_data.sort(key=lambda x: (x["תאריך"] == "לא ידוע", x["תאריך"]), reverse=True)

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
        df = df.sort_values("סכום_נומרי", ascending=False)
    elif sort_on == "ספק":
        df = df.sort_values("ספק")

    # Drop the helper numeric column before display
    display_df = df.drop(columns=["סכום_נומרי"])

    st.dataframe(
        display_df,
        column_config={
            "קישור": st.column_config.LinkColumn("📂 פתח", width="small"),
            "סכום": st.column_config.TextColumn("💰 סכום", width="small"),
            "תאריך": st.column_config.DateColumn("📅 תאריך", format="YYYY-MM-DD", width="medium"),
            "ספק": st.column_config.TextColumn("🏢 ספק", width="medium"),
            "סוג": st.column_config.TextColumn("🏷️ קטגוריה", width="medium"),
            "עסקי": st.column_config.TextColumn("👤/🏢", width="small"),
            "מקור": st.column_config.TextColumn("📄 קובץ מקורי", width="medium"),
        },
        width="stretch",
        hide_index=True,
    )
    
    if st.button("🔄 רענן רשימה", icon="🔄"):
        st.rerun()


if __name__ == "__main__":
    if _require_password():
        main()
